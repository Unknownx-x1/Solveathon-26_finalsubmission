from flask import Flask, render_template
from flask_cors import CORS
import os
from auth import auth_bp

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_secret_key')

# Register the authentication blueprint
app.register_blueprint(auth_bp)

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
