from flask import Blueprint, render_template

hotel_bp = Blueprint('hotel', __name__, url_prefix='/hotel')

@hotel_bp.route('/')
def dashboard():
    return "<h1>Hotel Shuttle Service - Under Construction</h1><a href='/'>Back to Portal</a>"