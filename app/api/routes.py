from flask import jsonify
from app import app

@app.route('/api')
def hello_world():
    return jsonify(message="Hello from Flask!")