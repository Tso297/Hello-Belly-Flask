import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app import db
from datetime import datetime

class User(db.Model):
    id = db.Column(db.String(255), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    appointments = db.relationship('Appointment', backref='user', lazy=True)

class Doctor(db.Model):
    id = db.Column(db.String(255), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    appointments = db.relationship('Appointment', backref='doctor', lazy=True)
    time_slots = db.relationship('TimeSlot', backref='doctor', lazy=True)  # Added relationship

class Appointment(db.Model):
    id = db.Column(db.String(255), primary_key=True)
    date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=True)  # Make this nullable
    purpose = db.Column(db.String(255), nullable=False)
    doctor_id = db.Column(db.String(255), db.ForeignKey('doctor.id'), nullable=False)
    user_id = db.Column(db.String(255), db.ForeignKey('user.id'), nullable=False)
    meeting_url = db.Column(db.String(255), nullable=False)
    moderator_url = db.Column(db.String(255), nullable=False)
    meeting_password = db.Column(db.String(255), nullable=False)
    is_time_off = db.Column(db.Boolean, default=False)

    def to_dict(self):
        user = User.query.get(self.user_id)
        doctor = Doctor.query.get(self.doctor_id)
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'end_date': self.end_date.isoformat() if self.end_date else None,  # Include this
            'purpose': self.purpose,
            'doctor': {
                'id': doctor.id,
                'name': doctor.name,
                'email': doctor.email
            },
            'user': {
                'id': user.id,
                'name': user.name,
                'email': user.email
            },
            'meeting_url': self.meeting_url,
            'moderator_url': self.moderator_url,
            'meeting_password': self.meeting_password,
            'is_time_off': self.is_time_off,
        }

class TimeSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.String(255), db.ForeignKey('doctor.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    appointment_id = db.Column(db.String(255), db.ForeignKey('appointment.id'), nullable=True)

class Class(db.Model):
    id = db.Column(db.String(255), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    day_of_week = db.Column(db.String(255), nullable=False)  # e.g., 'Monday', 'Tuesday', etc.
    time = db.Column(db.Time, nullable=False)
    link = db.Column(db.String(255), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'day_of_week': self.day_of_week,
            'time': self.time.isoformat(),
            'link': self.link
        }
    
class UploadedFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    doctor_id = db.Column(db.String(255), db.ForeignKey('doctor.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    doctor = db.relationship('Doctor', backref='uploaded_files')