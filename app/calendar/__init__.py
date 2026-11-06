from flask import Blueprint


calendar_bp = Blueprint("calendar", __name__)

from app.calendar import routes