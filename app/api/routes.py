import os
from flask import Blueprint, request, jsonify, redirect, make_response
from app import app, db
from app.models import UserSession, User, Appointment
import logging, time, jwt, requests, base64, hashlib, hmac
from . import api
from datetime import datetime, timedelta
from flask_cors import cross_origin, CORS
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint
import random
import string

logging.basicConfig(level=logging.DEBUG)

CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

DOCTOR_EMAIL = "TORCSH30@gmail.com"
appointments = []

CLIENT_ID = 'OAADD7FsTk6Wi0FG6nhvwg'
CLIENT_SECRET = 'ARCngsGPAYstjyQQB2iH4tQuqkNE08JA'
REDIRECT_URI = 'http://localhost:5000/api/callback'
SECRET_TOKEN = 'lj2nchtOTl64t2cysVYLfA'
AUTHORIZATION_BASE_URL = 'https://zoom.us/oauth/authorize'
TOKEN_URL = 'https://zoom.us/oauth/token'
API_BASE_URL = 'https://api.zoom.us/v2'
SENDINBLUE_API_KEY = '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'  # Your Sendinblue API key
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

def generate_random_string(length=12):
    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for i in range(length))

@app.route('/api/schedule_meeting', methods=['POST'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def schedule_meeting():
    data = request.json
    date = data.get('date')
    purpose = data.get('purpose')
    doctor_key = data.get('doctor')
    user_email = data.get('email')

    if not all([date, purpose, doctor_key, user_email]):
        return jsonify({'error': 'Missing data'}), 400

    meeting_id = generate_random_string()
    meeting_password = generate_random_string(8)
    meeting_url = f"https://meet.jit.si/{meeting_id}"
    moderator_url = f"https://meet.jit.si/{meeting_id}#config.password={meeting_password}"

    subject = f"Meeting Scheduled: {purpose}"
    body = f"Meeting Details:\n\nPurpose: {purpose}\nDate and Time: {date}\nMeeting URL: {meeting_url}\n\nPlease join the meeting at the specified time."

    moderator_body = f"Meeting Details:\n\nPurpose: {purpose}\nDate and Time: {date}\nMeeting URL: {meeting_url}\nModerator URL: {moderator_url}\nMeeting Password: {meeting_password}\n\nPlease join the meeting at the specified time."

    appointment = {
        "id": meeting_id,
        "date": date,
        "purpose": purpose,
        "doctor": doctor_key,
        "user_email": user_email,
        "meeting_url": meeting_url,
        "moderator_url": moderator_url,
        "meeting_password": meeting_password
    }
    appointments.append(appointment)

    send_email(DOCTOR_EMAIL, subject, moderator_body)
    send_email(user_email, subject, body)

    return jsonify({'message': 'Meeting scheduled successfully', 'meeting_url': meeting_url})

@app.route('/api/appointments', methods=['GET'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def list_appointments():
    user_email = request.args.get('email')
    user_appointments = [a for a in appointments if a['user_email'] == user_email]
    return jsonify({'appointments': user_appointments})

@app.route('/api/appointments/<appointment_id>', methods=['DELETE'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def delete_appointment(appointment_id):
    global appointments
    appointments = [a for a in appointments if a['id'] != appointment_id]
    return jsonify({'message': 'Appointment deleted successfully'})

@app.route('/api/appointments/<appointment_id>', methods=['PUT'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def update_appointment(appointment_id):
    data = request.json
    for appointment in appointments:
        if appointment['id'] == appointment_id:
            appointment['date'] = data.get('date', appointment['date'])
            appointment['purpose'] = data.get('purpose', appointment['purpose'])
            appointment['doctor'] = data.get('doctor', appointment['doctor'])
            appointment['user_email'] = data.get('email', appointment['user_email'])

            subject = f"Updated Meeting: {appointment['purpose']}"
            body = f"Updated Meeting Details:\n\nPurpose: {appointment['purpose']}\nDate and Time: {appointment['date']}\nMeeting URL: {appointment['meeting_url']}\n\nPlease join the meeting at the specified time."
            send_email(DOCTOR_EMAIL, subject, body)
            send_email(appointment['user_email'], subject, body)

            return jsonify({'message': 'Appointment updated successfully'})
    return jsonify({'error': 'Appointment not found'}), 404

def send_email(to_email, subject, body):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = SENDINBLUE_API_KEY
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

    sender = {"email": "your-email@example.com", "name": "Your Name"}  # Replace with your verified Sendinblue sender email and name
    receivers = [{"email": to_email}]

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=receivers,
        sender=sender,
        subject=subject,
        text_content=body
    )

    try:
        api_response = api_instance.send_transac_email(send_smtp_email)
        pprint(api_response)
    except ApiException as e:
        print(f"Failed to send email to {to_email}: {e}")

@app.route('/api/doctor_appointments', methods=['GET'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def list_doctor_appointments():
    doctor_email = request.args.get('email')
    if not doctor_email:
        return jsonify({'error': 'Doctor email is missing'}), 400

    appointments = Appointment.query.filter(Appointment.doctor.in_(['doctor1', 'doctor2'])).all()
    return jsonify({'appointments': [appointment.to_dict() for appointment in appointments]})