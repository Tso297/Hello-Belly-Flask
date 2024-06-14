import os
from flask import Blueprint, request, jsonify, redirect, make_response, send_from_directory
from app import app, db
from app.models import User, Appointment, Doctor, TimeSlot, Class, UploadedFile, Message, Chat
import logging, time, jwt, requests, base64, hashlib, hmac, random, string
from . import api
from datetime import datetime, timedelta
from flask_cors import cross_origin, CORS
import smtplib
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint
from dotenv import load_dotenv
from openai import OpenAI
import openai
import uuid
from werkzeug.utils import secure_filename

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

load_dotenv()

logging.basicConfig(level=logging.DEBUG)

CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# cred = credentials.Certificate('path/to/serviceAccountKey.json')
# firebase_admin.initialize_app(cred)
# firestore_db = firestore.client()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')
SECRET_TOKEN = os.getenv('SECRET_TOKEN')
AUTHORIZATION_BASE_URL = os.getenv('AUTHORIZATION_BASE_URL')
TOKEN_URL = os.getenv('TOKEN_URL')
API_BASE_URL = os.getenv('API_BASE_URL')
SENDINBLUE_API_KEY = os.getenv('SENDINBLUE_API_KEY')  # Your Sendinblue API key
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'}

api = Blueprint('api', __name__, url_prefix='/api')
classes = []
appointments = []
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)



app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_jitsi_link():
    random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f'https://meet.jit.si/{random_string}'

def generate_timeslots_for_doctor(doctor_id):
    start_time = datetime(2024, 1, 1, 9, 0)
    end_time = datetime(2024, 12, 31, 17, 0)

    slots = []
    while start_time < end_time:
        app.logger.debug(f"Generating time slot for {doctor_id} at {start_time}")
        slots.append(TimeSlot(
            doctor_id=doctor_id,
            start_time=start_time,
            is_available=True
        ))
        start_time += timedelta(minutes=30)

    db.session.bulk_save_objects(slots)
    db.session.commit()
    app.logger.info(f"Time slots generated for doctor {doctor_id}")

def generate_full_day_slots(date):
    """Generate all possible slots for a given date from 9:00 AM to 5:00 PM."""
    start_time = datetime.combine(date, datetime.min.time()) + timedelta(hours=9)
    end_time = datetime.combine(date, datetime.min.time()) + timedelta(hours=17)
    slots = []
    while start_time < end_time:
        slots.append(start_time)
        start_time += timedelta(minutes=30)
    return slots

def get_taken_slots(doctor_id, date):
    start_day = datetime.combine(date, datetime.min.time())
    end_day = start_day + timedelta(days=1)
    taken_slots = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date >= start_day,
        Appointment.date < end_day
    ).all()
    return [appointment.date for appointment in taken_slots]

@api.route('/')
def home():
    app.logger.info('Home route accessed')
    return 'Welcome to the Zoom Integration'

def encode_credentials(client_id, client_secret):
    credentials = f"{client_id}:{client_secret}"
    base64_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    return base64_credentials

def generate_random_string(length=12):
    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for i in range(length))

@app.route('/api/schedule_meeting', methods=['POST'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def schedule_meeting():
    data = request.json
    date_str = data.get('date')
    purpose = data.get('purpose')
    doctor_id = data.get('doctor')
    user_email = data.get('email')
    user_name = data.get('name')

    app.logger.debug(f"Received data: {data}")

    if not all([date_str, purpose, doctor_id, user_email, user_name]):
        app.logger.error('Missing data in schedule_meeting request')
        return jsonify({'error': 'Missing data'}), 400

    # Parse the date and subtract 4 hours
    date = datetime.fromisoformat(date_str) - timedelta(hours=4)
    app.logger.debug(f"Parsed date (adjusted): {date}")

    # Check if the slot is available
    time_slot = TimeSlot.query.filter_by(doctor_id=doctor_id, start_time=date, is_available=True).first()
    if not time_slot:
        app.logger.error("Time slot is already booked")
        return jsonify({'error': 'Time slot is already booked'}), 400

    meeting_id = generate_random_string()
    meeting_password = generate_random_string(8)
    meeting_url = f"https://meet.jit.si/{meeting_id}"
    moderator_url = f"https://meet.jit.si/{meeting_id}#config.password={meeting_password}"

    subject = f"Meeting Scheduled: {purpose}"

    user = User.query.filter_by(email=user_email).first()
    if not user:
        user = User(id=generate_random_string(), email=user_email, name=user_name)
        db.session.add(user)
        db.session.commit()
    else:
        user.name = user_name  # Update the name if it already exists

    doctor = Doctor.query.filter_by(id=doctor_id).first()
    if not doctor:
        app.logger.error("Doctor not found")
        return jsonify({'error': 'Doctor not found'}), 404

    appointment = Appointment(
        id=meeting_id,
        date=date,
        purpose=purpose,
        doctor_id=doctor.id,
        user_id=user.id,
        meeting_url=meeting_url,
        moderator_url=moderator_url,
        meeting_password=meeting_password
    )
    db.session.add(appointment)

    # Update the TimeSlot to mark it as booked
    time_slot.is_available = False
    time_slot.appointment_id = appointment.id
    db.session.commit()

    body = f"""
    Meeting Details:
    Doctor: {doctor.name}
    Purpose: {purpose}
    Date and Time: {date}
    Meeting URL: {meeting_url}
    
    Please join the meeting at the specified time.
    """

    moderator_body = f"""
    Meeting Details:
    Patient: {user.name}
    Purpose: {purpose}
    Date and Time: {date}
    Meeting URL: {meeting_url}
    Moderator URL: {moderator_url}
    Meeting Password: {meeting_password}
    
    Please join the meeting at the specified time.
    """

    app.logger.info(f"Meeting scheduled successfully: {appointment.to_dict()}")

    send_email(doctor.email, subject, moderator_body)
    send_email(user_email, subject, body)

    return jsonify({'message': 'Meeting scheduled successfully', 'appointment': appointment.to_dict()})

@app.route('/api/appointments', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def list_appointments():
    user_email = request.args.get('email')
    if not user_email:
        app.logger.error('Missing user email in request')
        return jsonify({'error': 'Missing user email'}), 400

    user = User.query.filter_by(email=user_email).first()
    if not user:
        app.logger.warning(f'User with email {user_email} not found')
        return jsonify({'appointments': []})

    appointments = Appointment.query.filter_by(user_id=user.id).all()
    app.logger.info(f"Appointments retrieved for user {user_email}: {[a.to_dict() for a in appointments]}")
    return jsonify({'appointments': [a.to_dict() for a in appointments]})

@app.route('/api/appointments', methods=['POST'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def schedule_appointment():
    data = request.json
    doctor_id = data['doctor_id']
    user_id = data['user_id']
    date = datetime.fromisoformat(data['date'])
    purpose = data['purpose']
    meeting_url = data['meeting_url']
    moderator_url = data['moderator_url']
    meeting_password = data['meeting_password']

    time_slot = TimeSlot.query.filter_by(doctor_id=doctor_id, start_time=date, is_available=True).first()

    if not time_slot:
        return jsonify({'error': 'Time slot is not available'}), 400

    appointment = Appointment(
        id=generate_random_string(),
        date=date,
        purpose=purpose,
        doctor_id=doctor_id,
        user_id=user_id,
        meeting_url=meeting_url,
        moderator_url=moderator_url,
        meeting_password=meeting_password
    )

    db.session.add(appointment)
    time_slot.is_available = False
    time_slot.appointment_id = appointment.id
    db.session.commit()

    return jsonify(appointment.to_dict()), 201

@app.route('/api/appointments/<appointment_id>', methods=['DELETE'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def cancel_appointment(appointment_id):
    appointment = Appointment.query.get(appointment_id)

    if not appointment:
        return jsonify({'error': 'Appointment not found'}), 404

    user = User.query.get(appointment.user_id)
    doctor = Doctor.query.get(appointment.doctor_id)

    subject = f"Meeting Canceled: {appointment.purpose}"
    body = f"""
    Your meeting has been canceled.
    Meeting Details:
    Doctor: {doctor.name}
    Purpose: {appointment.purpose}
    Date and Time: {appointment.date}
    Meeting URL: {appointment.meeting_url}
    """

    moderator_body = f"""
    The meeting has been canceled.
    Meeting Details:
    Patient: {user.name}
    Purpose: {appointment.purpose}
    Date and Time: {appointment.date}
    Meeting URL: {appointment.meeting_url}
    Moderator URL: {appointment.moderator_url}
    Meeting Password: {appointment.meeting_password}
    """

    send_email(doctor.email, subject, moderator_body)
    send_email(user.email, subject, body)

    time_slots = TimeSlot.query.filter_by(appointment_id=appointment_id).all()
    for time_slot in time_slots:
        time_slot.is_available = True
        time_slot.appointment_id = None

    db.session.delete(appointment)
    db.session.commit()

    return jsonify({'message': 'Appointment canceled successfully'}), 200


@app.route('/api/appointments/<appointment_id>', methods=['PUT'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def reschedule_appointment(appointment_id):
    data = request.json
    app.logger.debug(f"Received data for rescheduling: {data}")
    new_date = data.get('date')

    if not new_date:
        app.logger.error("New date is required")
        return jsonify({'error': 'New date is required'}), 400

    appointment = Appointment.query.get(appointment_id)
    if not appointment:
        app.logger.error(f"Appointment with ID {appointment_id} not found")
        return jsonify({'error': 'Appointment not found'}), 404

    try:
        new_datetime = datetime.fromisoformat(new_date) - timedelta(hours=4)
    except ValueError as e:
        app.logger.error(f"Invalid date format: {e}")
        return jsonify({'error': 'Invalid date format'}), 400

    app.logger.debug(f"New datetime for rescheduling: {new_datetime}")

    new_timeslot = TimeSlot.query.filter_by(doctor_id=appointment.doctor_id, start_time=new_datetime, is_available=True).first()
    if not new_timeslot:
        app.logger.error(f"New time slot not found or not available")
        return jsonify({'error': 'The new time slot is not available'}), 400

    old_timeslot = TimeSlot.query.filter_by(doctor_id=appointment.doctor_id, start_time=appointment.date).first()
    if old_timeslot:
        old_timeslot.is_available = True
        old_timeslot.appointment_id = None

    new_timeslot.is_available = False
    new_timeslot.appointment_id = appointment.id

    appointment.date = new_datetime
    db.session.commit()

    user = User.query.get(appointment.user_id)
    doctor = Doctor.query.get(appointment.doctor_id)

    subject = f"Meeting Rescheduled: {appointment.purpose}"
    body = f"""
    Your meeting has been rescheduled.
    New Meeting Details:
    Doctor: {doctor.name}
    Purpose: {appointment.purpose}
    Date and Time: {new_datetime}
    Meeting URL: {appointment.meeting_url}
    """

    moderator_body = f"""
    The meeting has been rescheduled.
    New Meeting Details:
    Patient: {user.name}
    Purpose: {appointment.purpose}
    Date and Time: {new_datetime}
    Meeting URL: {appointment.meeting_url}
    Moderator URL: {appointment.moderator_url}
    Meeting Password: {appointment.meeting_password}
    """

    send_email(doctor.email, subject, moderator_body)
    send_email(user.email, subject, body)

    return jsonify({'message': 'Appointment rescheduled successfully', 'appointment': appointment.to_dict()})


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

@app.route('/api/doctors', methods=['POST'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def create_doctor():
    data = request.json
    name = data.get('name')
    email = data.get('email')

    if not all([name, email]):
        return jsonify({'error': 'Missing data'}), 400

    doctor = Doctor(id=generate_random_string(), name=name, email=email)
    db.session.add(doctor)
    db.session.commit()

    generate_timeslots_for_doctor(doctor.id)

    return jsonify({'message': 'Doctor created successfully', 'doctor': {'id': doctor.id, 'name': doctor.name, 'email': doctor.email}}), 201

@app.route('/api/admin/doctors', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def admin_list_doctors():
    doctors = Doctor.query.all()
    app.logger.info(f"Doctors retrieved: {[doctor.name for doctor in doctors]}")
    return jsonify({'doctors': [{'id': doctor.id, 'name': doctor.name, 'email': doctor.email} for doctor in doctors]})

@app.route('/api/admin/doctors', methods=['POST'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def admin_create_doctor():
    data = request.json
    admin_email = request.args.get('admin_email')

    if admin_email != 'torcsh30@gmail.com':
        app.logger.error('Unauthorized access attempt')
        return jsonify({'error': 'Unauthorized access'}), 403

    name = data.get('name')
    email = data.get('email')

    if not all([name, email]):
        app.logger.error('Missing data in request')
        return jsonify({'error': 'Missing data'}), 400

    doctor = Doctor(id=generate_random_string(), name=name, email=email)
    db.session.add(doctor)
    db.session.commit()

    generate_timeslots_for_doctor(doctor.id)  # Ensure this line is present

    app.logger.info(f"Doctor created successfully: {doctor}")
    return jsonify({'message': 'Doctor created successfully', 'doctor': {'id': doctor.id, 'name': doctor.name, 'email': doctor.email}}), 201

@app.route('/api/doctors', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def list_doctors():
    doctors = Doctor.query.all()
    app.logger.info(f"Doctors retrieved: {[doctor.name for doctor in doctors]}")
    return jsonify({'doctors': [{'id': doctor.id, 'name': doctor.name, 'email': doctor.email} for doctor in doctors]})

@app.route('/api/is_doctor', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def is_doctor():
    user_email = request.args.get('email')
    if not user_email:
        app.logger.error('Missing user email in request')
        return jsonify({'error': 'Missing user email'}), 400

    doctor = Doctor.query.filter_by(email=user_email).first()
    is_doctor = doctor is not None

    app.logger.info(f"Checked if user is a doctor: {user_email}, is_doctor: {is_doctor}")
    return jsonify({'is_doctor': is_doctor})

@app.route('/api/available_slots', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def get_available_slots():
    doctor_id = request.args.get('doctor_id')
    date_str = request.args.get('date')

    if not all([doctor_id, date_str]):
        app.logger.error('Missing data in available_slots request')
        return jsonify({'error': 'Missing data'}), 400

    date = datetime.fromisoformat(date_str)
    start_time = date.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = date.replace(hour=17, minute=0, second=0, microsecond=0)

    all_slots = [start_time + timedelta(minutes=30 * i) for i in range(17)]  # 9 AM to 5 PM inclusive

    taken_slots = TimeSlot.query.filter_by(doctor_id=doctor_id, is_available=False).filter(
        TimeSlot.start_time >= start_time,
        TimeSlot.start_time < end_time
    ).all()

    taken_times = {slot.start_time for slot in taken_slots}
    available_slots = [slot for slot in all_slots if slot not in taken_times]

    return jsonify({'available_slots': [slot.isoformat() for slot in available_slots]})


@app.route('/api/doctor_appointments', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def doctor_appointments():
    doctor_id = request.args.get('doctor_id')
    app.logger.info(f"Received doctor_appointments request for doctor_id: {doctor_id}")
    if not doctor_id:
        app.logger.error("Missing doctor_id in doctor_appointments request")
        return jsonify({'error': 'Missing doctor_id'}), 400

    appointments = Appointment.query.filter_by(doctor_id=doctor_id).all()
    app.logger.info(f"Fetched appointments: {appointments}")
    return jsonify({'appointments': [appointment.to_dict() for appointment in appointments]})


@app.route('/api/doctor_by_email', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def get_doctor_by_email():
    email = request.args.get('email')
    app.logger.info(f"Received get_doctor_by_email request for email: {email}")
    if not email:
        app.logger.error("Missing email in get_doctor_by_email request")
        return jsonify({'error': 'Missing email'}), 400

    doctor = Doctor.query.filter_by(email=email).first()
    if not doctor:
        app.logger.error("Doctor not found")
        return jsonify({'error': 'Doctor not found'}), 404

    app.logger.info(f"Fetched doctor: {doctor}")
    return jsonify({'id': doctor.id, 'name': doctor.name, 'email': doctor.email})

@app.route('/api/request_time_off', methods=['POST'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def request_time_off():
    data = request.json
    date_str = data.get('date')
    end_date_str = data.get('end_date')
    purpose = data.get('purpose')
    doctor_id = data.get('doctor')
    user_email = data.get('email')
    user_name = data.get('name')

    app.logger.debug(f"Received data: {data}")

    if not all([date_str, end_date_str, purpose, doctor_id, user_email, user_name]):
        app.logger.error('Missing data in request_time_off request')
        return jsonify({'error': 'Missing data'}), 400

    start_date = datetime.fromisoformat(date_str) - timedelta(hours=4)
    end_date = datetime.fromisoformat(end_date_str) - timedelta(hours=4)
    app.logger.debug(f"Parsed dates (adjusted): {start_date} to {end_date}")

    doctor = Doctor.query.filter_by(id=doctor_id).first()
    if not doctor:
        app.logger.error(f"Doctor with ID {doctor_id} not found")
        return jsonify({'error': 'Doctor not found'}), 404

    user = User.query.filter_by(email=user_email).first()
    if not user:
        user = User(id=generate_random_string(), email=user_email, name=user_name)
        db.session.add(user)
        db.session.commit()

    user_id = user.id

    existing_appointments = Appointment.query.filter_by(doctor_id=doctor_id).filter(
        Appointment.date.between(start_date, end_date)
    ).all()
    if existing_appointments:
        app.logger.error(f"Some time slots within the range are already booked")
        return jsonify({'error': 'Some time slots within the range are already booked'}), 400

    appointment_id = generate_random_string()
    appointment = Appointment(
        id=appointment_id,
        date=start_date,
        end_date=end_date,
        purpose=purpose,
        doctor_id=doctor_id,
        user_id=user_id,
        meeting_url='N/A',
        moderator_url='N/A',
        meeting_password='N/A',
        is_time_off=True
    )
    db.session.add(appointment)

    current_time = start_date
    while current_time < end_date:
        time_slot = TimeSlot.query.filter_by(doctor_id=doctor_id, start_time=current_time).first()
        if not time_slot:
            time_slot = TimeSlot(doctor_id=doctor_id, start_time=current_time, is_available=False)
            db.session.add(time_slot)
        else:
            time_slot.is_available = False
        current_time += timedelta(minutes=30)

    db.session.commit()

    return jsonify({'message': 'Time off requested successfully'}), 201

@app.route('/api/request_time_off/<appointment_id>', methods=['PUT'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def reschedule_time_off(appointment_id):
    data = request.json
    new_start_date_str = data.get('new_start_date')
    new_end_date_str = data.get('new_end_date')
    app.logger.debug(f"Received data for rescheduling time off: {data}")

    if not all([new_start_date_str, new_end_date_str]):
        app.logger.error("New start date and end date are required")
        return jsonify({'error': 'New start date and end date are required'}), 400

    appointment = Appointment.query.get(appointment_id)
    if not appointment:
        app.logger.error(f"Appointment with ID {appointment_id} not found")
        return jsonify({'error': 'Appointment not found'}), 404

    try:
        new_start_datetime = datetime.fromisoformat(new_start_date_str) - timedelta(hours=4)
        new_end_datetime = datetime.fromisoformat(new_end_date_str) - timedelta(hours=4)
    except ValueError as e:
        app.logger.error(f"Invalid date format: {e}")
        return jsonify({'error': 'Invalid date format'}), 400

    app.logger.debug(f"New datetime for rescheduling: {new_start_datetime} to {new_end_datetime}")

    existing_appointments = Appointment.query.filter_by(doctor_id=appointment.doctor_id).filter(
        Appointment.date.between(new_start_datetime, new_end_datetime)
    ).all()
    if existing_appointments:
        app.logger.error(f"Some time slots within the range are already booked")
        return jsonify({'error': 'Some time slots within the range are already booked'}), 400

    old_time_slots = TimeSlot.query.filter_by(appointment_id=appointment.id).all()
    for time_slot in old_time_slots:
        time_slot.is_available = True
        time_slot.appointment_id = None

    current_time = new_start_datetime
    while current_time < new_end_datetime:
        time_slot = TimeSlot.query.filter_by(doctor_id=appointment.doctor_id, start_time=current_time).first()
        if not time_slot:
            time_slot = TimeSlot(doctor_id=appointment.doctor_id, start_time=current_time, is_available=False, appointment_id=appointment.id)
            db.session.add(time_slot)
        else:
            time_slot.is_available = False
            time_slot.appointment_id = appointment.id
        current_time += timedelta(minutes=30)

    appointment.date = new_start_datetime
    appointment.end_date = new_end_datetime
    db.session.commit()

    return jsonify({'message': 'Time off rescheduled successfully', 'appointment': appointment.to_dict()})


@app.route('/api/chatgpt', methods=['POST'])
@cross_origin(origins=['https://hello-belly-22577.web.app', 'http://localhost:5173', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def chatgpt_query():
    app.logger.info('chatgpt_query route accessed')
    data = request.json
    app.logger.debug(f"Received data: {data}")
    
    question = data.get('question')
    if not question:
        app.logger.error("Question parameter is required")
        return jsonify({"error": "Question parameter is required"}), 400

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"Answer the following question about pregnancy: {question}"}
            ]
        )
        answer = response.choices[0].message.content.strip()
        app.logger.debug(f"Generated answer: {answer}")
        return jsonify({"answer": answer})
    except Exception as e:
        app.logger.error(f"Error generating answer: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/youtube', methods=['GET'])
@cross_origin(origins=['https://hello-belly-22577.web.app', 'http://localhost:5173', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def youtube_search():
    app.logger.info('youtube_search route accessed')
    query = request.args.get('query')
    max_results = request.args.get('maxResults', 5)  # Default to 20 if not provided

    if not query:
        app.logger.error("Query parameter is required")
        return jsonify({"error": "Query parameter is required"}), 400

    app.logger.debug(f"Searching YouTube for query: {query}")
    url = f'https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&maxResults={max_results}&key={YOUTUBE_API_KEY}&type=video'
    response = requests.get(url)
    videos = response.json().get('items', [])
    
    video_data = [
        {
            'id': video['id']['videoId'],
            'title': video['snippet']['title'],
            'description': video['snippet']['description']
        }
        for video in videos
    ]
    
    app.logger.debug(f"Found videos: {video_data}")
    return jsonify({"videos": video_data})

@app.route('/api/classes', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def get_classes():
    try:
        classes = Class.query.all()
        return jsonify([class_instance.to_dict() for class_instance in classes])
    except Exception as e:
        app.logger.error(f"Error fetching classes: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/update_class/<class_id>', methods=['PUT'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def update_class(class_id):
    data = request.json
    try:
        class_instance = Class.query.get(class_id)
        if not class_instance:
            return jsonify({"error": "Class not found"}), 404

        class_instance.name = data.get('name', class_instance.name)
        class_instance.day_of_week = data.get('day_of_week', class_instance.day_of_week)
        class_instance.time = datetime.strptime(data['time'], '%H:%M').time()
        db.session.commit()
        return jsonify(class_instance.to_dict())
    except Exception as e:
        app.logger.error(f"Error updating class: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete_class/<class_id>', methods=['DELETE'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def delete_class(class_id):
    try:
        class_instance = Class.query.get(class_id)
        if not class_instance:
            return jsonify({"error": "Class not found"}), 404

        db.session.delete(class_instance)
        db.session.commit()
        return jsonify({"message": "Class deleted successfully"})
    except Exception as e:
        app.logger.error(f"Error deleting class: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/add_class', methods=['POST'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def add_class():
    data = request.json
    try:
        name = data['name']
        day_of_week = data['day_of_week']
        time = datetime.strptime(data['time'], '%H:%M').time()
        link = f"https://meet.jit.si/{uuid.uuid4()}"

        new_class = Class(id=str(uuid.uuid4()), name=name, day_of_week=day_of_week, time=time, link=link)
        db.session.add(new_class)
        db.session.commit()
        return jsonify(new_class.to_dict()), 201
    except Exception as e:
        app.logger.error(f"Error adding class: {e}")
        return jsonify({"error": str(e)}), 500

google_maps_key = os.getenv('VITE_GOOGLE_MAPS_API_KEY')    
print(f"Loaded Google Maps API key: {os.getenv('VITE_GOOGLE_MAPS_API_KEY')}")

@app.route('/api/google_maps_key', methods=['GET', 'POST'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def get_google_maps_key():
    google_maps_key = os.getenv('VITE_GOOGLE_MAPS_API_KEY')
    app.logger.debug(f"Fetching Google Maps API key: {google_maps_key}")
    if not google_maps_key:
        app.logger.error("Google Maps API key not found")
        return jsonify({'error': 'Google Maps API key not found'}), 404
    return jsonify({'google_maps_key': google_maps_key})

@app.route('/api/doctors/<doctor_id>', methods=['PUT'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def update_doctor(doctor_id):
    data = request.get_json()
    doctor = Doctor.query.get(doctor_id)
    if doctor:
        doctor.name = data.get('name', doctor.name)
        doctor.email = data.get('email', doctor.email)
        db.session.commit()
        return jsonify({"message": "Doctor updated successfully."}), 200
    return jsonify({"error": "Doctor not found."}), 404

@app.route('/api/doctors/<doctor_id>', methods=['DELETE'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def delete_doctor(doctor_id):
    try:
        TimeSlot.query.filter(TimeSlot.doctor_id == doctor_id).delete()

        Appointment.query.filter(Appointment.doctor_id == doctor_id).delete()

        Doctor.query.filter(Doctor.id == doctor_id).delete()

        db.session.commit()
        
        return jsonify({"message": "Doctor and all associated appointments and time slots deleted successfully."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/files', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def list_files():
    doctor_id = request.args.get('doctor_id')
    if not doctor_id:
        return jsonify({'error': 'Doctor ID is required'}), 400

    files = UploadedFile.query.filter_by(doctor_id=doctor_id).all()
    file_paths = [{'id': f.id, 'filename': f.filename, 'file_path': f.file_path} for f in files]
    return jsonify({'files': file_paths}), 200

@app.route('/api/upload', methods=['POST'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        return jsonify({'filePath': filename}), 200

    return jsonify({'error': 'File type not allowed'}), 400


@app.route('/api/rename_file', methods=['PUT'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def rename_file():
    file_id = request.json.get('file_id')
    new_file_name = request.json.get('new_file_name')
    if not file_id or not new_file_name:
        return jsonify({'error': 'File ID and new file name are required'}), 400

    file_record = UploadedFile.query.get(file_id)
    if not file_record:
        return jsonify({'error': 'File not found'}), 404

    old_path = file_record.file_path
    new_file_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(new_file_name))

    try:
        os.rename(old_path, new_file_path)
        file_record.filename = secure_filename(new_file_name)
        file_record.file_path = new_file_path
        db.session.commit()
        return jsonify({'message': 'File renamed successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete_file', methods=['DELETE'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def delete_file():
    file_id = request.json.get('file_id')
    if not file_id:
        return jsonify({'error': 'File ID is required'}), 400

    file_record = UploadedFile.query.get(file_id)
    if not file_record:
        return jsonify({'error': 'File not found'}), 404

    try:
        os.remove(file_record.file_path)
        db.session.delete(file_record)
        db.session.commit()
        return jsonify({'message': 'File deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/uploads/<filename>')
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def uploaded_file(filename):
    app.logger.debug(f"Serving file: {filename}")
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/sync_doctors', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def sync_doctors():
    try:
        doctors = Doctor.query.all()
        doctor_list = [{'id': doctor.id, 'name': doctor.name, 'email': doctor.email} for doctor in doctors]

        # Remove Firestore sync code

        return jsonify({'message': 'Doctors synced successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/search_users', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def search_users():
    term = request.args.get('term', '').lower()
    results = []

    if term:
        users = User.query.filter(User.name.ilike(f'%{term}%') | User.email.ilike(f'%{term}%')).all()
        doctors = Doctor.query.filter(Doctor.name.ilike(f'%{term}%') | Doctor.email.ilike(f'%{term}%')).all()

        results = [{'id': user.id, 'name': user.name, 'email': user.email, 'role': 'user'} for user in users]
        results += [{'id': doctor.id, 'name': doctor.name, 'email': doctor.email, 'role': 'doctor'} for doctor in doctors]

    return jsonify({'results': results})

@app.route('/api/chats', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def get_chats():
    user_id = request.args.get('userId')
    if not user_id:
        return jsonify({'error': 'User ID is required'}), 400

    sent_messages = Message.query.filter_by(sender_id=user_id).order_by(Message.timestamp.desc()).all()
    received_messages = Message.query.filter_by(receiver_id=user_id).order_by(Message.timestamp.desc()).all()

    chat_map = {}
    for message in sent_messages + received_messages:
        chat_id = message.thread_id
        if chat_id not in chat_map:
            other_user_id = message.receiver_id if message.sender_id == user_id else message.sender_id
            other_user = User.query.get(other_user_id) or Doctor.query.get(other_user_id)
            chat_map[chat_id] = {
                'id': chat_id,
                'otherUserName': other_user.name if other_user else 'Unknown',
                'receiverId': message.receiver_id,
                'timestamp': message.timestamp,
                'subject': message.subject,
                'lastMessage': message.message
            }
        else:
            chat_map[chat_id]['timestamp'] = max(chat_map[chat_id]['timestamp'], message.timestamp)

    sorted_chats = sorted(chat_map.values(), key=lambda x: x['timestamp'], reverse=True)
    return jsonify({'chats': sorted_chats})

@app.route('/api/messages', methods=['GET'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def get_messages():
    thread_id = request.args.get('threadId')
    if not thread_id:
        return jsonify({'error': 'Thread ID is required'}), 400

    messages = Message.query.filter_by(thread_id=thread_id).order_by(Message.timestamp.asc()).all()
    messages_data = []
    for message in messages:
        sender = User.query.get(message.sender_id) or Doctor.query.get(message.sender_id)
        messages_data.append({
            'id': message.id,
            'senderId': message.sender_id,
            'senderName': sender.name if sender else 'Unknown',
            'message': message.message,
            'timestamp': message.timestamp,
            'fileUrl': message.file_url,
            'fileName': message.file_name,
        })

    return jsonify({'messages': messages_data})

@app.route('/api/messages', methods=['POST'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def add_message():
    data = request.json
    sender_id = data['senderId']
    receiver_id = data['receiverId']
    message = data['message']
    subject = data['subject']
    thread_id = data['threadId']
    file_url = data.get('fileUrl')
    file_name = data.get('fileName')

    new_message = Message(
        id=str(uuid.uuid4()),
        sender_id=sender_id,
        receiver_id=receiver_id,
        message=message,
        subject=subject,
        thread_id=thread_id,
        timestamp=datetime.utcnow(),
        file_url=file_url,
        file_name=file_name,
    )
    db.session.add(new_message)
    db.session.commit()

    return jsonify({'message': 'Message added successfully'})

@app.route('/api/messages/<thread_id>', methods=['DELETE'])
@cross_origin(origins=['http://localhost:5173', 'https://hello-belly-22577.web.app', 'https://hello-belly-22577.firebaseapp.com/'], supports_credentials=True)
def delete_chat(thread_id):
    messages = Message.query.filter_by(thread_id=thread_id).all()
    for message in messages:
        db.session.delete(message)

    db.session.commit()

    return jsonify({'message': 'Chat deleted successfully'})