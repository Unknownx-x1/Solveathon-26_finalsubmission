import requests
import logging
from flask import Blueprint, jsonify, request, make_response
from bs4 import BeautifulSoup
import uuid
import os
import warnings

# Internal project imports
try:
    from vtop.session_manager import session_storage
    from vtop.parsers.credentials_parser import parse_credentials
    from vtop.parsers.profile_parser import parse_profile
except ImportError:
    from session_manager import session_storage
    from parsers.credentials_parser import parse_credentials
    from parsers.profile_parser import parse_profile

# Suppress only the InsecureRequestWarning for VIT's internal certificates
warnings.filterwarnings('ignore', category=requests.packages.urllib3.exceptions.InsecureRequestWarning)

auth_bp = Blueprint('auth_bp', __name__)
logger = logging.getLogger(__name__)

VTOP_BASE_URL = "https://vtopcc.vit.ac.in/vtop/"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0'
}

# ----------------------------------------
# LOGIN FUNCTION
# ----------------------------------------
def perform_vtop_login(api_session, csrf_token, username, password, captcha_text, session_id):
    """
    Executes the actual VTOP login request.
    """
    try:
        payload = {
            "_csrf": csrf_token,
            "username": username,
            "password": password,
            "captchaStr": captcha_text
        }
        
        login_url = VTOP_BASE_URL + "login"
        
        response = api_session.post(
            login_url, 
            data=payload, 
            headers=HEADERS, 
            verify=False, 
            timeout=20
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        login_form = soup.find('form', {'id': 'vtopLoginForm'})

        if not login_form:
            # Login successful: VTOP redirects or shows the home page
            authorized_id = username 
            auth_id_tag = soup.find('input', {'name': 'authorizedID'}) or soup.find('input', {'name': 'authorizedIDX'})
            if auth_id_tag and auth_id_tag.get('value'):
                 authorized_id = auth_id_tag.get('value')
            
            # Store student info in our session storage
            session_storage[session_id]['username'] = username
            session_storage[session_id]['authorized_id'] = authorized_id
            
            # Update CSRF token for subsequent requests
            new_csrf_tag = soup.find('input', {'name': '_csrf'})
            if new_csrf_tag and new_csrf_tag.get('value'):
                session_storage[session_id]['csrf_token'] = new_csrf_tag.get('value')
                logger.debug("Login success: %s, CSRF updated.", authorized_id)
            else:
                logger.debug("Login success: %s, but CSRF tag not found in response.", authorized_id)
            
            return True, authorized_id, 'success'
        else:
            # Login failed: VTOP returns the login page with an error message
            error_tag = soup.select_one("span.text-danger strong")
            error_msg = error_tag.get_text(strip=True) if error_tag else "Invalid credentials."
            logger.debug("Login failed: %s", error_msg)
            return False, error_msg, 'invalid_credentials'

    except Exception as e:
        logger.debug("Login exception: %s", str(e))
        return False, f"Connection error: {str(e)}", 'error'

# ----------------------------------------
# START LOGIN (GET CAPTCHA + CSRF)
# ----------------------------------------
@auth_bp.route('/start-login', methods=['GET', 'POST'])
def start_login():
    """
    Initializes a new session, fetches the CSRF token and Captcha.
    """
    session_id = str(uuid.uuid4())
    api_session = requests.Session()
    
    try:
        # Step 1: Initialize the login page
        res = api_session.get(
            VTOP_BASE_URL + "open/page", 
            headers=HEADERS, 
            verify=False,
            timeout=15
        )
        csrf_pre = BeautifulSoup(res.text, 'html.parser').find('input', {'name': '_csrf'}).get('value')
        
        # Step 2: Setup login context
        res = api_session.post(
            VTOP_BASE_URL + "prelogin/setup", 
            data={'_csrf': csrf_pre, 'flag': 'VTOP'}, 
            headers=HEADERS,
            verify=False,
            timeout=15
        )
        csrf_login = BeautifulSoup(res.text, 'html.parser').find('input', {'name': '_csrf'}).get('value')
        
        # Step 3: Get the Captcha image source
        captcha_res = api_session.get(
            VTOP_BASE_URL + "get/new/captcha", 
            headers=HEADERS,
            verify=False,
            timeout=15
        )
        captcha_soup = BeautifulSoup(captcha_res.text, 'html.parser')
        captcha_img = captcha_soup.find('img')
        
        if not captcha_img:
             return jsonify({'status': 'failure', 'message': 'Could not fetch captcha'}), 500
             
        captcha_src = captcha_img['src']

        # Store the session and current CSRF in our server-side storage
        session_storage[session_id] = {
            'session': api_session, 
            'csrf_token': csrf_login,
            'created_at': uuid.uuid1() # timestamp placeholder
        }
        
        return jsonify({
            'status': 'captcha_ready', 
            'session_id': session_id, 
            'captcha_image_data': captcha_src
        })
        
    except Exception as e:
        logger.error(f"Error in start_login: {e}")
        return jsonify({'status': 'failure', 'message': f"Failed to connect to VTOP: {str(e)}"}), 500

# ----------------------------------------
# LOGIN ATTEMPT
# ----------------------------------------
@auth_bp.route('/login-attempt', methods=['POST'])
def login_attempt():
    """
    Submits student credentials and captcha to VTOP.
    """
    data = request.json
    s_id = data.get('session_id')
    
    if not s_id or s_id not in session_storage:
        return jsonify({'status': 'failure', 'message': 'Session expired. Please refresh.'}), 400
        
    success, result, code = perform_vtop_login(
        session_storage[s_id]['session'], 
        session_storage[s_id]['csrf_token'], 
        data.get('username'), 
        data.get('password'), 
        data.get('captcha'), 
        s_id
    )
    
    if success:
        resp = make_response(jsonify({
            'status': 'success', 
            'message': f'Welcome, {result}!', 
            'session_id': s_id
        }))
        # Set persistent cookie for subsequent API calls
        resp.set_cookie(
            'session_id', 
            s_id, 
            httponly=True, 
            samesite='Lax',
            secure=request.is_secure # Set secure if on HTTPS
        )
        return resp
        
    return jsonify({'status': code, 'message': result})

# ----------------------------------------
# STUDENT DATA APIS (Restored)
# ----------------------------------------
@auth_bp.route('/api/credentials', methods=['GET'])
def get_credentials_api():
    session_id = request.cookies.get('session_id') or request.args.get('session_id')
    if not session_id or session_id not in session_storage:
        return jsonify({'status': 'failure', 'message': 'Invalid or expired session.'}), 401

    api_session = session_storage[session_id]['session']
    try:
        creds_url = VTOP_BASE_URL + "proctor/viewStudentCredentials"
        csrf_token = session_storage[session_id]['csrf_token']
        authorized_id = session_storage[session_id].get('authorized_id') or session_storage[session_id].get('username')
        
        headers = HEADERS.copy()
        headers['Referer'] = VTOP_BASE_URL + "home"
        
        response = api_session.post(
            creds_url, 
            data={'_csrf': csrf_token, 'authorizedID': authorized_id}, 
            headers=headers, 
            verify=False, 
            timeout=20
        )
        response.raise_for_status()
        data = parse_credentials(response.text)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error fetching credentials for session {session_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@auth_bp.route('/api/profile', methods=['GET'])
def get_profile_api():
    session_id = request.cookies.get('session_id') or request.args.get('session_id')
    if not session_id or session_id not in session_storage:
        return jsonify({'status': 'failure', 'message': 'Invalid session.'}), 401

    api_session = session_storage[session_id]['session']
    try:
        profile_url = VTOP_BASE_URL + "studentsRecord/StudentProfileAllView"
        csrf_token = session_storage[session_id]['csrf_token']
        authorized_id = session_storage[session_id].get('authorized_id')
        
        headers = HEADERS.copy()
        headers['Referer'] = VTOP_BASE_URL + "home"
        
        response = api_session.post(
            profile_url, 
            data={'_csrf': csrf_token, 'authorizedID': authorized_id}, 
            headers=headers, 
            verify=False, 
            timeout=20
        )
        response.raise_for_status()

        data = parse_profile(response.text)
        
        # In case the parser fails or is incomplete, ensure we have the reg_no
        if 'educational' not in data: data['educational'] = {}
        if not data['educational'].get('reg_no'):
            data['educational']['reg_no'] = session_storage[session_id].get('username', authorized_id)
            
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error fetching profile for session {session_id}: {e}")
        return jsonify({'status': 'error', 'message': f"Could not fetch student details: {str(e)}"}), 500

@auth_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    session_id = (request.json or {}).get('session_id') or request.cookies.get('session_id')
    if session_id in session_storage:
        del session_storage[session_id]
        
    resp = make_response(jsonify({'status': 'success'}))
    resp.delete_cookie('session_id')
    return resp

@auth_bp.route('/session-check', methods=['GET'])
def session_check():
    session_id = request.cookies.get('session_id')
    if not session_id:
        return jsonify({'vtop': False, 'valid': False})
    if session_id not in session_storage:
        return jsonify({'vtop': True, 'valid': False})
    return jsonify({'vtop': True, 'valid': True})