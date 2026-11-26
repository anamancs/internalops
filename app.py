
import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, render_template

# Load environment variables from the root .env file
load_dotenv()

from extensions import db
from auth import auth_bp, init_auth, User
from fleet_app import fleet_bp, GpsLog
from acs_quotation_app.quotation_app import (
    quotation_bp,
    init_app as init_quotation_app,
    Quotation
)
from receipt_app import receipt_bp, Receipt
from chatbot_app import chatbot_bp, KnowledgeDoc
from finance_app import finance_bp, Transaction
from directory_app import directory_bp, UIDepartment


app = Flask(__name__)


@app.context_processor
def inject_now():
    return {'now': datetime.now}


# 1. Set up configurations
init_auth(app)
init_quotation_app(app)


# 2. Bind the shared database to the app
db.init_app(app)


# 3. Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(fleet_bp)
app.register_blueprint(quotation_bp)
app.register_blueprint(receipt_bp)
app.register_blueprint(chatbot_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(directory_bp)


@app.route('/')
def landing_page():
    return render_template('landing.html')


# 4. Create database tables and seed the default admin
with app.app_context():

    # Ensure the quotation app instance directory exists
    os.makedirs(
        os.path.join(app.root_path, 'acs_quotation_app', 'instance'),
        exist_ok=True
    )

    db.create_all()

    # Read administrator credentials from .env
    admin_username = os.getenv('ACS_ADMIN_USERNAME')
    admin_password = os.getenv('ACS_ADMIN_PASSWORD')

    # Only create the admin if the account does not already exist
    if admin_username and not User.query.filter_by(
        username=admin_username
    ).first():

        if not admin_password:
            raise RuntimeError(
                "ACS_ADMIN_PASSWORD is missing from the .env file."
            )

        admin = User(
            username=admin_username,
            role='admin'
        )

        admin.set_password(admin_password)

        db.session.add(admin)
        db.session.commit()

        print("Default administrator account created successfully.")

    elif not admin_username:
        print(
            "WARNING: ACS_ADMIN_USERNAME is missing from .env. "
            "Default administrator seeding was skipped."
        )


if __name__ == '__main__':
    app.run(debug=True)
