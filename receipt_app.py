import os
import cloudinary
import cloudinary.uploader
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required
from extensions import db
from datetime import datetime
import os
import json
from dotenv import load_dotenv

receipt_bp = Blueprint('receipt', __name__, url_prefix='/receipts')

# Load environment variables
#load_dotenv()

from pathlib import Path
from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent / '.env'

load_dotenv(dotenv_path=ENV_FILE, override=True)

#print("ENV FILE BEING LOADED:", ENV_FILE)
#print("ACS DRIVERS RAW:", os.getenv("ACS_DRIVERS_JSON"))

# Load the driver directory from .env
try:
    DRIVER_DIRECTORY = json.loads(
        os.getenv('ACS_DRIVERS_JSON', '{}')
    )

    if not isinstance(DRIVER_DIRECTORY, dict):
        raise ValueError("ACS_DRIVERS_JSON must contain a JSON object.")

    # Normalize email addresses
    DRIVER_DIRECTORY = {
        email.strip().lower(): name.strip()
        for email, name in DRIVER_DIRECTORY.items()
        if isinstance(email, str) and isinstance(name, str)
    }

except (json.JSONDecodeError, ValueError) as e:
    raise RuntimeError(
        f"Unable to load ACS driver directory: {e}"
    )
#print("ACS LOADED DRIVERS:", DRIVER_DIRECTORY)# Configure Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

# ✅ THE DRIVER ROSTER (Add all your drivers here)
# Format: "email@domain.com": "Driver Full Name"
#DRIVER_DIRECTORY = {
#    "felix@anamancs.com": "Felix Anaman",
#    "driver2@anamancs.com": "John Doe",
#    "driver3@anamancs.com": "Jane Smith",
#}

# --- Database Model ---
class Receipt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_name = db.Column(db.String(100), nullable=False)
    driver_email = db.Column(db.String(120), nullable=False) # ✅ Changed to email
    date = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    payment_method = db.Column(db.String(50), default='Unknown')
    card_last_four = db.Column(db.String(4), nullable=True)
    image_url = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), default='Pending') 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



@receipt_bp.route('/api/verify-driver', methods=['POST'])
def verify_driver():
    data = request.get_json(silent=True) or {}

    driver_name = (data.get('driver_name') or '').strip()
    driver_email = (data.get('driver_email') or '').strip().lower()

    if not driver_name or not driver_email:
        return jsonify({
            'valid': False,
            'message': 'Please enter your name and work email.'
        }), 400

    registered_name = DRIVER_DIRECTORY.get(driver_email)

    if registered_name and registered_name.strip().casefold() == driver_name.casefold():
        return jsonify({
            'valid': True,
            'message': 'Your driver details have been verified.'
        })

    return jsonify({
        'valid': False,
        'message': 'The email address does not match the selected driver name.'
    }), 200

# --- Public Routes ---

@receipt_bp.route('/upload', methods=['GET', 'POST'], strict_slashes=False)
def upload():

    # GET request: display the upload form without validating driver details.
    if request.method == 'GET':
        return render_template('upload.html', drivers=DRIVER_DIRECTORY)

    # POST request: validate the submitted driver details.
    driver_name = request.form.get('driver_name', '').strip()
    driver_email = request.form.get('driver_email', '').strip().lower()

    registered_name = DRIVER_DIRECTORY.get(driver_email)

    if (
        not registered_name
        or registered_name.strip().casefold() != driver_name.casefold()
    ):
        flash(
            'Your driver name and email address do not match our records. '
            'Please check your details.',
            'danger'
        )
        return redirect(url_for('receipt.upload'))

    # Retrieve the remaining form fields.
    date = request.form.get('date', '').strip()
    amount = request.form.get('amount', '').strip()
    category = request.form.get('category', '').strip()
    payment_method = request.form.get('payment_method', '').strip()
    card_last_four = request.form.get('card_last_four', '').strip()
    file = request.files.get('receipt_image')

    if not file or not file.filename:
        flash('Please select a receipt image.', 'danger')
        return redirect(url_for('receipt.upload'))

    if not date or not amount or not category or not payment_method:
        flash('Please complete all required receipt details.', 'danger')
        return redirect(url_for('receipt.upload'))

    if payment_method in ['Personal Card', 'Business Card']:
        if not card_last_four.isdigit() or len(card_last_four) != 4:
            flash('Please enter the last four digits of your card.', 'danger')
            return redirect(url_for('receipt.upload'))

    try:
        amount_value = float(amount)

        if amount_value <= 0:
            raise ValueError("Amount must be greater than zero.")

        upload_result = cloudinary.uploader.upload(
            file,
            folder="acs_receipts/"
        )

        image_url = upload_result.get('secure_url')

        if not image_url:
            raise ValueError("Cloudinary did not return an image URL.")

        new_receipt = Receipt(
            driver_name=registered_name,
            driver_email=driver_email,
            date=date,
            amount=amount_value,
            category=category,
            payment_method=payment_method,
            card_last_four=(
                card_last_four
                if payment_method in ['Personal Card', 'Business Card']
                else None
            ),
            image_url=image_url
        )

        db.session.add(new_receipt)
        db.session.commit()

        flash('Receipt uploaded successfully!', 'success')
        return redirect(url_for('receipt.upload'))

    except Exception as e:
        db.session.rollback()
        print(f"Receipt upload error: {e}")
        flash('Your receipt could not be uploaded. Please try again.', 'danger')
        return redirect(url_for('receipt.upload'))


# In receipt_app.py
@receipt_bp.route('/track', strict_slashes=False)
def track():
    return render_template('track.html', drivers=DRIVER_DIRECTORY)

# ... (Keep everything at the top the same: imports, cloudinary config, DRIVER_DIRECTORY, Model) ...

@receipt_bp.route('/api/track', methods=['POST'])
def api_track():
    #email = request.json.get('email')
    email = (request.json.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'Email required'}), 400
    
    # Backend verification (Double check that the email is in our authorized roster)
    if email not in DRIVER_DIRECTORY:
        return jsonify({'error': 'Unauthorized'}), 403
    
    #receipts = Receipt.query.filter(Receipt.driver_email.ilike(f"%{email}%")).order_by(Receipt.created_at.desc()).all()
    receipts = Receipt.query.filter_by(driver_email=email).order_by(Receipt.created_at.desc()).all()
    
    results = []
    for r in receipts:
        results.append({
            'id': r.id,
            'date': r.date,
            'amount': f"${r.amount:.2f}",
            'category': r.category,
            'status': r.status,
            'image_url': r.image_url
        })
    return jsonify({'receipts': results})

# ... (Keep the rest of the file exactly the same) ...

# --- Admin Routes ---
@receipt_bp.route('/admin', strict_slashes=False)
@login_required
def admin():
    receipts = Receipt.query.order_by(Receipt.created_at.desc()).all()
    return render_template('admin_approvals.html', receipts=receipts)

@receipt_bp.route('/api/status/<int:id>', methods=['POST'])
@login_required
def update_status(id):
    receipt = Receipt.query.get_or_404(id)
    new_status = request.json.get('status')
    if new_status in ['Approved', 'Rejected', 'Paid']:
        receipt.status = new_status
        db.session.commit()
        return jsonify({'message': 'Status updated'})
    return jsonify({'error': 'Invalid status'}), 400