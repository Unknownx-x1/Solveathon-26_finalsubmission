from bs4 import BeautifulSoup 
 
def parse_profile(html_content): 
    """ 
    Parses the VTOP Student Profile HTML response. 
    Returns a dictionary with profile sections. 
    """ 
    if not html_content: 
        return {} 
 
    soup = BeautifulSoup(html_content, 'html.parser') 
    profile_data = { 
        'personal': {}, 
        'educational': {}, 
        'family': {'father': {}, 'mother': {}}, 
        'proctor': {}, 
        'hostel': {} 
    } 
 
    # Helper to safely get text from a row (for simple unique keys) 
    def get_row_value(table, key_name): 
        if not table: return None 
        key_td = table.find('td', string=lambda text: text and key_name.lower() in text.lower()) 
        if key_td: 
            value_td = key_td.find_next_sibling('td') 
            if value_td: 
                return value_td.get_text(strip=True) 
        return None 
 
    # --- Personal Info --- 
    personal_table = soup.find('div', id='collapseOne') 
    if personal_table: 
        profile_data['personal'] = { 
            'name': get_row_value(personal_table, 'STUDENT NAME'), 
            'app_no': get_row_value(personal_table, 'APPLICATION NUMBER') or get_row_value(personal_table, 'APP NO'), 
            'reg_no': get_row_value(personal_table, 'REGISTER NO') or get_row_value(personal_table, 'REG NO'),
            'dob': get_row_value(personal_table, 'DATE OF BIRTH'), 
            'gender': get_row_value(personal_table, 'GENDER'), 
            'blood_group': get_row_value(personal_table, 'BLOOD GROUP'), 
            'email': get_row_value(personal_table, 'EMAIL'), 
            'mobile': get_row_value(personal_table, 'MOBILE NUMBER'), 
            'native_state': get_row_value(personal_table, 'NATIVE STATE') 
        } 
        img_tag = soup.find('img', class_='img border border-primary') 
        if img_tag: 
            profile_data['personal']['photo_url'] = img_tag.get('src') 
 
    # --- Educational Info --- 
    edu_table = soup.find('div', id='collapseTwo') 
    if edu_table: 
        profile_data['educational'] = { 
            'reg_no': get_row_value(edu_table, 'REGISTER NO') or get_row_value(edu_table, 'REG NO'), 
            'school': get_row_value(edu_table, 'SCHOOL NAME'), 
            'board': get_row_value(edu_table, 'BOARD'), 
            'medium': get_row_value(edu_table, 'MEDIUM'), 
            'year_passing': get_row_value(edu_table, 'YEAR OF PASSING') 
        } 
    
    # Fallback for reg_no if not in collapseTwo
    if not profile_data['educational'].get('reg_no'):
        reg_no_global = get_row_value(soup, 'REGISTER NO') or get_row_value(soup, 'REG NO') or get_row_value(soup, 'REGISTRATION NO')
        if reg_no_global:
            if 'educational' not in profile_data: profile_data['educational'] = {}
            profile_data['educational']['reg_no'] = reg_no_global 
    # --- Family Info --- 
    family_table = soup.find('div', id='collapseThree') 
    if family_table: 
        rows = family_table.find_all('tr') 
        current_section = 'father' # Default 
         
        for row in rows: 
            text = row.get_text(strip=True).upper() 
            # Switch context based on header rows 
            if 'FATHER DETAILS' in text: 
                current_section = 'father' 
                continue 
            elif 'MOTHER DETAILS' in text: 
                current_section = 'mother' 
                continue 
             
            cells = row.find_all('td') 
            if len(cells) >= 2: 
                key = cells[0].get_text(strip=True).upper() 
                val = cells[1].get_text(strip=True) 
                 
                target = profile_data['family'][current_section] 
                 
                if 'NAME' in key and 'STREET' not in key and 'AREA' not in key: 
                     target['name'] = val 
                elif 'OCCUPATION' in key: target['occupation'] = val 
                elif 'ORGANIZATION' in key: target['organization'] = val 
                elif 'MOBILE' in key: target['mobile'] = val 
                elif 'EMAIL' in key: target['email'] = val 
 
    # --- Proctor Info --- 
    proctor_table = soup.find('div', id='collapseFour') 
    if proctor_table: 
        profile_data['proctor'] = { 
            'name': get_row_value(proctor_table, 'FACULTY NAME'), 
            'designation': get_row_value(proctor_table, 'FACULTY DESIGNATION'), 
            'cabin': get_row_value(proctor_table, 'CABIN'), 
            'email': get_row_value(proctor_table, 'FACULTY EMAIL'), 
            'mobile': get_row_value(proctor_table, 'FACULTY MOBILE NUMBER') 
        } 
 
    # --- Hostel Info --- 
    hostel_table = soup.find('div', id='collapseFive') 
    if hostel_table: 
        profile_data['hostel'] = { 
            'block': get_row_value(hostel_table, 'Block'), 
            'room': get_row_value(hostel_table, 'Room No'), 
            'bed_type': get_row_value(hostel_table, 'Bed Type'), 
            'mess': get_row_value(hostel_table, 'Mess Information') 
        } 
 
    return profile_data 
