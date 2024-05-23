import os
from flask import Blueprint, request, jsonify, redirect, make_response
from app import app, db
from app.models import UserSession
import logging, time, jwt, requests, base64, hashlib, hmac
from . import api
from datetime import datetime, timedelta
from flask_cors import cross_origin, CORS

logging.basicConfig(level=logging.DEBUG)

CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)


CLIENT_ID = 'OAADD7FsTk6Wi0FG6nhvwg'
CLIENT_SECRET = 'ARCngsGPAYstjyQQB2iH4tQuqkNE08JA'
REDIRECT_URI = 'http://localhost:5000/api/callback'
SECRET_TOKEN = 'lj2nchtOTl64t2cysVYLfA'
AUTHORIZATION_BASE_URL = 'https://zoom.us/oauth/authorize'
TOKEN_URL = 'https://zoom.us/oauth/token'
API_BASE_URL = 'https://api.zoom.us/v2'
########################################################################################
@api.route('/')
def home():
    app.logger.info('Home route accessed')
    return 'Welcome to the Zoom Integration'

def generate_jwt_token():
    try:
        payload = {
            'iss': CLIENT_ID,  # Your Zoom API Key
            'exp': int(time.time()) + 3600
        }
        logging.debug(f"JWT Payload: {payload}")
        token = jwt.encode(payload, CLIENT_SECRET, algorithm='HS256')  # Your Zoom API Secret
        logging.debug(f"Generated JWT Token: {token}")

        # Decode the token to verify its content
        decoded = jwt.decode(token, CLIENT_SECRET, algorithms=['HS256'])
        logging.debug(f"Decoded JWT Token: {decoded}")

        return token
    except Exception as e:
        logging.error(f"Error generating JWT token: {str(e)}")
        raise e

# Decode the token for verification
token = generate_jwt_token()
decoded = jwt.decode(token, CLIENT_SECRET, algorithms=['HS256'])
print(decoded)

def encode_credentials(client_id, client_secret):
    credentials = f"{client_id}:{client_secret}"
    base64_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    return base64_credentials

@app.route('/login')
def login():
    zoom_authorize_url = f"https://zoom.us/oauth/authorize?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    logging.info(f"Redirecting to Zoom authorization URL: {zoom_authorize_url}")
    return redirect(zoom_authorize_url)

@app.route('/authorize_zoom')
def authorize_zoom():
    zoom_authorize_url = f"https://zoom.us/oauth/authorize?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    return redirect(zoom_authorize_url)

@app.route('/api/callback', methods=['GET'])
def callback():
    code = request.args.get('code')
    logging.debug(f"Received authorization code: {code}")

    if not code:
        logging.error("Authorization code is missing")
        return jsonify({'error': 'Authorization code is missing'}), 400

    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    try:
        response = requests.post(TOKEN_URL, data=payload, headers=headers)
        response.raise_for_status()
        response_data = response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to get token from Zoom: {str(e)}")
        return jsonify({'error': 'Failed to get token from Zoom', 'details': str(e)}), 500

    access_token = response_data.get('access_token')
    refresh_token = response_data.get('refresh_token')
    expires_in = response_data.get('expires_in')

    logging.debug(f"Access token content: {access_token}")

    user_session = UserSession.query.filter_by(id='default_user').first()
    if not user_session:
        user_session = UserSession(id='default_user')
        db.session.add(user_session)

    user_session.access_token = access_token
    user_session.refresh_token = refresh_token
    user_session.expiry = datetime.utcnow() + timedelta(seconds=expires_in)
    db.session.commit()

    logging.info(f"Zoom authorization successful. Tokens saved for user: {user_session.id}")

    return redirect('http://localhost:3000')

@app.route('/api/create_meeting', methods=['POST'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def create_meeting():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        logging.error("Authorization header is missing")
        return jsonify({'error': 'Authorization header is missing'}), 401

    access_token = auth_header.split(' ')[1]
    logging.debug(f"Access token received: {access_token}")

    data = request.json
    logging.debug(f"Meeting creation request data: {data}")

    topic = data.get('topic', 'New Meeting')
    start_time = data.get('start_time')
    duration = data.get('duration', 30)

    payload = {
        'topic': topic,
        'type': 2,
        'duration': duration,
        'timezone': 'UTC',
        'start_time': start_time
    }
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    logging.debug(f"Meeting creation payload: {payload}")
    logging.debug(f"Meeting creation headers: {headers}")

    try:
        response = requests.post('https://api.zoom.us/v2/users/me/meetings', json=payload, headers=headers)
        response.raise_for_status()
        logging.info("Meeting created successfully")
        return jsonify(response.json())
    except requests.RequestException as e:
        logging.error(f"Failed to create meeting: {str(e)}")
        if response.status_code == 401:
            logging.error(f"Unauthorized access. Ensure your access token is correct and not expired.")
        return jsonify({'error': 'Failed to create meeting', 'details': str(e)}), 500

@app.route('/get_zoom_token', methods=['POST'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def get_zoom_token():
    user_session = UserSession.query.filter_by(id='default_user').first()
    if user_session and user_session.access_token:
        return jsonify({'access_token': user_session.access_token})
    else:
        return jsonify({'error': 'User session not found or access token missing'}), 401


@app.route('/api/profile')
def profile():
    app.logger.info('Profile route accessed')
    user_session = UserSession.query.filter_by(id='default_user').first()
    if not user_session or not user_session.access_token:
        app.logger.warning('Unauthorized access to profile route')
        return jsonify({'error': 'Unauthorized'}), 401
    
    headers = {'Authorization': f'Bearer {user_session.access_token}'}
    response = requests.get('https://api.zoom.us/v2/users/me', headers=headers)
    if response.status_code != 200:
        app.logger.error('Error fetching profile: %s - %s', response.status_code, response.text)
        return jsonify({'error': 'Failed to fetch profile from Zoom'}), response.status_code
    
    return jsonify(response.json())

def refresh_zoom_token(user_session):
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': user_session.refresh_token,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    app.logger.info("Refreshing Zoom access token")
    app.logger.debug(f"Payload: {payload}")
    app.logger.debug(f"Headers: {headers}")

    try:
        response = requests.post(TOKEN_URL, data=payload, headers=headers)
        response.raise_for_status()
        app.logger.info("Token refresh successful")
    except requests.RequestException as e:
        app.logger.error(f"Failed to refresh Zoom token: {str(e)}")
        raise Exception('Failed to refresh Zoom token')

    response_data = response.json()
    access_token = response_data.get('access_token')
    expires_in = response_data.get('expires_in')
    refresh_token = response_data.get('refresh_token')

    app.logger.info(f"New access token received: {access_token}")
    app.logger.info(f"Token expires in: {expires_in} seconds")

    user_session.access_token = access_token
    user_session.refresh_token = refresh_token
    user_session.expiry = datetime.utcnow() + timedelta(seconds=expires_in)
    db.session.commit()

    return access_token




@app.route('/')
def index():
    app.logger.info('Index route accessed')
    return redirect(REDIRECT_URI)

@api.route('/webhook', methods=['POST'])
@cross_origin()
def webhook():
    zoom_signature = request.headers.get('x-zm-signature')
    request_body = request.get_data()
    
    # Verify the signature
    computed_signature = hmac.new(SECRET_TOKEN.encode(), request_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_signature, zoom_signature):
        app.logger.error('Invalid signature on webhook request')
        return jsonify({'error': 'Invalid signature'}), 400

    event_data = request.json
    # Handle the event data
    app.logger.info('Webhook event data: %s', event_data)

    return jsonify({'status': 'success'})
