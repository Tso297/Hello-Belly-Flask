from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from flask_moment import Moment

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
moment = Moment(app)

CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

from . import models
from .api import api

app.register_blueprint(api)
