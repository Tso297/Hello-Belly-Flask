import os
import hmac
import hashlib
import base64
import requests
from flask import Blueprint, request, jsonify, redirect, session, url_for, make_response
from flask_cors import cross_origin
from . import api
from app import app
import logging

logging.basicConfig(level=logging.DEBUG)
app.secret_key = os.urandom(24)

CLIENT_ID = 'OAADD7FsTk6Wi0FG6nhvwg'
CLIENT_SECRET = 'ARCngsGPAYstjyQQB2iH4tQuqkNE08JA'
REDIRECT_URI = 'http://localhost:5000/api/callback'
SECRET_TOKEN = 'lj2nchtOTl64t2cysVYLfA'
AUTHORIZATION_BASE_URL = 'https://zoom.us/oauth/authorize'
TOKEN_URL = 'https://zoom.us/oauth/token'
API_BASE_URL = 'https://api.zoom.us/v2'

@api.route('/')
def home():
    print('Home route accessed')
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
    
    if not access_token or not refresh_token:
        app.logger.error('Access token or refresh token is missing in the response')
        return jsonify({'error': 'Failed to get complete token from Zoom'}), 500

    session['zoom_access_token'] = access_token
    session['zoom_refresh_token'] = refresh_token

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
    if 'zoom_access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    headers = {'Authorization': f'Bearer {session["zoom_access_token"]}'}
    response = requests.get('https://api.zoom.us/v2/users/me', headers=headers)
    if response.status_code != 200:
        print(f'Error fetching profile: {response.status_code} - {response.text}')
        return jsonify({'error': 'Failed to fetch profile from Zoom'}), response.status_code
    
    return jsonify(response.json())

@api.route('/create_meeting', methods=['OPTIONS', 'POST'])
@cross_origin()
def create_meeting():
    print(f'Received request to create meeting. Method: {request.method}')
    print(f'Session: {session}')
    print(f'Access token in session: {session.get("access_token")}')

    if request.method == 'OPTIONS':
        print('Handling OPTIONS request')
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = 'http://localhost:5173'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.status_code = 204
        return response

    if 'access_token' not in session:
        print('Unauthorized access to create_meeting route')
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    print(f'Request JSON data: {data}')
    topic = data.get('topic', 'New Meeting')
    start_time = data.get('start_time')
    duration = data.get('duration', 30)  # Default duration 30 minutes

    print(f'Creating meeting with topic: {topic}, start_time: {start_time}, duration: {duration}')

    payload = {
        'topic': topic,
        'type': 2,  # Scheduled meeting
        'start_time': start_time,
        'duration': duration,
        'timezone': 'UTC',
    }

    headers = {
        'Authorization': f'Bearer {session["access_token"]}',
        'Content-Type': 'application/json'
    }

    response = requests.post(f'{API_BASE_URL}/users/me/meetings', json=payload, headers=headers)
    print(f'Response from create meeting request: {response.status_code} - {response.text}')
    
    if response.status_code != 201:
        print('Error creating meeting:', response.text)
        return jsonify({'error': 'Failed to create meeting'}), response.status_code

    return jsonify(response.json())

@app.route('/get_zoom_token', methods=['POST'])
def get_zoom_token():
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

    session['zoom_access_token'] = access_token

    app.logger.info('Access token received: %s', access_token)

    return jsonify({'access_token': access_token})

@app.route('/')
def index():
    return redirect(REDIRECT_URI)

@api.route('/webhook', methods=['POST'])
@cross_origin()
def webhook():
    zoom_signature = request.headers.get('x-zm-signature')
    request_body = request.get_data()
    
    # Verify the signature
    computed_signature = hmac.new(SECRET_TOKEN.encode(), request_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_signature, zoom_signature):
        print('Invalid signature on webhook request')
        return jsonify({'error': 'Invalid signature'}), 400

    event_data = request.json
    # Handle the event data
    print(f'Webhook event data: {event_data}')

    return jsonify({'status': 'success'})