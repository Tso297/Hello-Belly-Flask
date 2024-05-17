import os
import hmac
import hashlib
import base64
import requests
from flask import Blueprint, request, jsonify, redirect, session, url_for, make_response
from flask_cors import cross_origin
from . import api
from app import app

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

@api.route('/login')
def login():
    authorization_url = f"{AUTHORIZATION_BASE_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    print(f'Redirecting to: {authorization_url}')
    return redirect(authorization_url)

@api.route('/callback')
def callback():
    code = request.args.get('code')
    print(f'Callback route accessed with code: {code}')
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
    }
    headers = {
        'Authorization': f'Basic {base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()}',
    }
    response = requests.post(TOKEN_URL, data=payload, headers=headers)
    print(f'Response from token request: {response.status_code} - {response.text}')
    response_data = response.json()
    session['access_token'] = response_data['access_token']
    session['refresh_token'] = response_data['refresh_token']
    print('Access token and refresh token stored in session')
    print(f'Access token: {session["access_token"]}')
    return redirect(url_for('.profile'))

@api.route('/profile')
def profile():
    print('Profile route accessed')
    headers = {
        'Authorization': f'Bearer {session["access_token"]}'
    }
    response = requests.get(f'{API_BASE_URL}/users/me', headers=headers)
    print(f'Response from profile request: {response.status_code} - {response.text}')
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

@api.route('/zoom_token', methods=['GET'])
@cross_origin()
def generate_zoom_token():
    print('Generating Zoom token')
    if 'access_token' not in session:
        print('Unauthorized access to generate_zoom_token route')
        return jsonify({'error': 'Unauthorized'}), 401

    meeting_number = request.args.get('meeting_number')
    role = int(request.args.get('role', 0))  # 0 for participant, 1 for host

    print(f'Generating token for meeting_number: {meeting_number}, role: {role}')

    payload = {
        'meetingNumber': meeting_number,
        'role': role,
        'userName': 'your user name',
        'apiKey': CLIENT_ID,
        'userEmail': 'your user email',
        'passWord': '',
    }

    response = requests.post(f'{API_BASE_URL}/meetings/{meeting_number}', json=payload, headers={
        'Authorization': f'Bearer {session["access_token"]}',
        'Content-Type': 'application/json',
    })

    print(f'Response from token generation request: {response.status_code} - {response.text}')
    return jsonify(response.json())

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