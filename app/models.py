from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, String, LargeBinary, DateTime, ForeignKey
from datetime import datetime
from app import db

class UserSession(db.Model):
    __tablename__ = 'sessions'
    id = db.Column(db.String(255), primary_key=True)
    access_token = db.Column(db.String(4096))
    refresh_token = db.Column(db.String(4096))
    expiry = db.Column(db.DateTime)
    appointments = db.relationship('Appointment', backref='user', lazy=True)

    def __init__(self, id, access_token, refresh_token, expiry):
        self.id = id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expiry = expiry

    def __repr__(self):
        return f'<UserSession id={self.id} access_token={self.access_token[:10]}... refresh_token={self.refresh_token[:10]}... expiry={self.expiry}>'
    
class User(db.Model):
    id = db.Column(db.String(255), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    appointments = db.relationship('Appointment', backref='user', lazy=True)

class Appointment(db.Model):
    id = db.Column(db.String(255), primary_key=True)
    date = db.Column(db.DateTime, nullable=False)
    purpose = db.Column(db.String(255), nullable=False)
    doctor = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.String(255), db.ForeignKey('user.id'), nullable=False)
    meeting_url = db.Column(db.String(255), nullable=False)
    moderator_url = db.Column(db.String(255), nullable=False)
    meeting_password = db.Column(db.String(255), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'purpose': self.purpose,
            'doctor': self.doctor,
            'user_id': self.user_id,
            'meeting_url': self.meeting_url,
            'moderator_url': self.moderator_url,
            'meeting_password': self.meeting_password,
        }