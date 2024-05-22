import os
from flask import Blueprint, request, jsonify, redirect, make_response
from app import app, db
from app.models import UserSession
import hmac
import hashlib
import base64
import requests
import logging
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

def encode_credentials(client_id, client_secret):
    credentials = f"{client_id}:{client_secret}"
    base64_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    return base64_credentials

@app.route('/api/callback', methods=['GET'])
def callback():
    app.logger.debug('Callback route called')
    code = request.args.get('code')
    if not code:
        app.logger.error('Authorization code is missing in the callback request')
        return jsonify({'error': 'Authorization code is missing'}), 400

    app.logger.info('Authorization code received: %s', code)

    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI
    }

    encoded_credentials = encode_credentials(CLIENT_ID, CLIENT_SECRET)
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    app.logger.info('Sending POST request to Zoom token endpoint with payload: %s', payload)

    try:
        response = requests.post(TOKEN_URL, data=payload, headers=headers)
        app.logger.debug('Zoom token endpoint response status: %s', response.status_code)
        app.logger.debug('Zoom token endpoint response headers: %s', response.headers)
        app.logger.debug('Zoom token endpoint response body: %s', response.text)
        response.raise_for_status()  # Raise an exception for HTTP errors
    except requests.RequestException as e:
        app.logger.error('Exception occurred while requesting token from Zoom: %s', str(e))
        return jsonify({'error': 'Failed to get token from Zoom', 'details': response.text}), 500

    response_data = response.json()
    access_token = response_data.get('access_token')
    refresh_token = response_data.get('refresh_token')
    expiry = datetime.utcnow() + timedelta(seconds=response_data.get('expires_in', 3600))

    if not access_token or not refresh_token:
        app.logger.error('Access token or refresh token is missing in the response')
        return jsonify({'error': 'Failed to get complete token from Zoom'}), 500

    # Store access token, refresh token, and expiry in the database
    user_session = UserSession(id='default_user', access_token=access_token, refresh_token=refresh_token, expiry=expiry)
    db.session.add(user_session)
    db.session.commit()

    app.logger.info('Access token received: %s', access_token)
    app.logger.info('Refresh token received: %s', refresh_token)

    # Send the authorization code back to the opener window
    return f"""
    <script>
      window.opener.postMessage({{code: '{code}'}}, "http://localhost:5173");
      window.close();
    </script>
    """

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
    encoded_credentials = encode_credentials(CLIENT_ID, CLIENT_SECRET)
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': user_session.refresh_token
    }

    app.logger.info('Sending POST request to Zoom token endpoint with payload: %s', payload)

    try:
        response = requests.post(TOKEN_URL, data=payload, headers=headers)
        app.logger.debug('Zoom token endpoint response status: %s', response.status_code)
        app.logger.debug('Zoom token endpoint response headers: %s', response.headers)
        app.logger.debug('Zoom token endpoint response body: %s', response.text)
        response.raise_for_status()  # Raise an exception for HTTP errors
    except requests.RequestException as e:
        app.logger.error('Exception occurred while requesting token from Zoom: %s', str(e))
        raise

    response_data = response.json()
    access_token = response_data.get('access_token')
    refresh_token = response_data.get('refresh_token')

    if not access_token or not refresh_token:
        app.logger.error('Access token or refresh token is missing in the response')
        raise ValueError('Failed to get complete token from Zoom')

    expiry = datetime.utcnow() + timedelta(seconds=response_data.get('expires_in', 3600))

    user_session.access_token = access_token
    user_session.refresh_token = refresh_token
    user_session.expiry = expiry

    db.session.add(user_session)
    db.session.commit()

    app.logger.info('Access token received: %s', access_token)
    return access_token

@app.route('/api/create_meeting', methods=['POST'])
def create_meeting():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Unauthorized'}), 401

    access_token = auth_header.split(' ')[1]
    user_session = UserSession.query.filter_by(access_token=access_token).first()
    if not user_session or user_session.expiry < datetime.utcnow():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    topic = data.get('topic', 'New Meeting')
    start_time = data.get('start_time')
    duration = data.get('duration', 30)

    payload = {
        'topic': topic,
        'type': 2,
        'start_time': start_time,
        'duration': duration,
        'timezone': 'UTC',
    }

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    response = requests.post('https://api.zoom.us/v2/users/me/meetings', json=payload, headers=headers)
    if response.status_code != 201:
        return jsonify({'error': 'Failed to create meeting'}), response.status_code

    return jsonify(response.json())

@app.route('/get_zoom_token', methods=['POST'])
def get_zoom_token():
    app.logger.info('get_zoom_token route accessed')
    encoded_credentials = encode_credentials(CLIENT_ID, CLIENT_SECRET)
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    payload = {
        'grant_type': 'client_credentials'
    }

    app.logger.info('Sending POST request to Zoom token endpoint with payload: %s', payload)

    try:
        response = requests.post(TOKEN_URL, data=payload, headers=headers)
        app.logger.debug('Zoom token endpoint response status: %s', response.status_code)
        app.logger.debug('Zoom token endpoint response headers: %s', response.headers)
        app.logger.debug('Zoom token endpoint response body: %s', response.text)
        response.raise_for_status()  # Raise an exception for HTTP errors
    except requests.RequestException as e:
        app.logger.error('Exception occurred while requesting token from Zoom: %s', str(e))
        return jsonify({'error': 'Failed to get token from Zoom', 'details': response.text}), 500

    response_data = response.json()
    access_token = response_data.get('access_token')

    if not access_token:
        app.logger.error('Access token is missing in the response')
        return jsonify({'error': 'Failed to get complete token from Zoom'}), 500

    expiry = datetime.utcnow() + timedelta(seconds=response_data.get('expires_in', 3600))

    user_session = UserSession.query.filter_by(id='default_user').first()
    if not user_session:
        user_session = UserSession(id='default_user', access_token=access_token, refresh_token='', expiry=expiry)
    else:
        user_session.access_token = access_token
        user_session.expiry = expiry

    db.session.add(user_session)
    db.session.commit()

    app.logger.info('Access token received: %s', access_token)

    return jsonify({'access_token': access_token})

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
