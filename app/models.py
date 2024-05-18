from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, String, LargeBinary, DateTime
from datetime import datetime
from app import db

class UserSession(db.Model):
    __tablename__ = 'sessions'
    id = db.Column(db.String(255), primary_key=True)
    access_token = db.Column(db.String(4096))  # Adjusted length
    refresh_token = db.Column(db.String(4096))  # Adjusted length
    expiry = db.Column(db.DateTime)

    def __init__(self, id, access_token, refresh_token, expiry):
        self.id = id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expiry = expiry