import os
import requests
import pandas as pd
from io import StringIO
from flask import Blueprint, render_template, request, jsonify
from flask_login import current_user
from extensions import db
import time # ✅ Added for cache busting

directory_bp = Blueprint('directory', __name__, url_prefix='/directory')

class UIDepartment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(150), unique=True, nullable=False)
    primary_admin = db.Column(db.String(100), nullable=False)
    primary_email = db.Column(db.String(120), nullable=False)
    primary_phone = db.Column(db.String(20), nullable=True)
    secondary_admin = db.Column(db.String(100), nullable=True)
    secondary_email = db.Column(db.String(120), nullable=True)
    secondary_phone = db.Column(db.String(20), nullable=True)
    booking_count = db.Column(db.Integer, default=0)
    last_booking_date = db.Column(db.String(20), nullable=True)

@directory_bp.route('/')
def index():
    return render_template('directory.html', is_admin=current_user.is_authenticated)

@directory_bp.route('/api/list', methods=['GET'])
def get_list():
    depts = UIDepartment.query.order_by(UIDepartment.department.asc()).all()
    results = []
    for d in depts:
        results.append({
            'id': d.id,
            'department': d.department,
            'primary_admin': d.primary_admin,
            'primary_email': d.primary_email,
            'primary_phone': d.primary_phone or '',
            'secondary_admin': d.secondary_admin or '',
            'secondary_email': d.secondary_email or '',
            'secondary_phone': d.secondary_phone or '',
            'booking_count': d.booking_count,
            'last_booking_date': d.last_booking_date or ''
        })
    return jsonify({'departments': results})

@directory_bp.route('/api/sync', methods=['POST'])
def sync_directory():
    sheet_url = os.environ.get("GOOGLE_DIRECTORY_SHEET_URL")
    if not sheet_url:
        return jsonify({'error': 'GOOGLE_DIRECTORY_SHEET_URL not configured in .env'}), 500

    try:
        bust_url = f"{sheet_url}&t={int(time.time())}"
        response = requests.get(bust_url)
        response.raise_for_status()
        
        df = pd.read_csv(StringIO(response.text))
        df.columns = [c.strip() for c in df.columns]

        required_cols = ['Department', 'Primary Admin', 'Primary Email', 'Booking Count']
        if not all(col in df.columns for col in required_cols):
            return jsonify({'error': 'Missing columns in Google Sheet.'}), 400

        # ✅ FIX 1: Remove blank rows
        df = df.dropna(subset=['Department'])
        
        # ✅ FIX 2: Clean up whitespace
        df['Department'] = df['Department'].astype(str).str.strip()

        # ✅ FIX 3: Drop duplicates (keep the first one it finds)
        df = df.drop_duplicates(subset=['Department'], keep='first')

        # Clear old data
        UIDepartment.query.delete()
        db.session.commit()

        count = 0
        for _, row in df.iterrows():
            dept_name = str(row['Department']).strip()
            if not dept_name or dept_name.lower() == 'nan': continue
            
            # Format date to YYYY-MM-DD
            raw_date = row.get('Last Booking Date')
            formatted_date = ''
            if not pd.isna(raw_date) and str(raw_date).strip() != '':
                try:
                    formatted_date = pd.to_datetime(raw_date).strftime('%Y-%m-%d')
                except:
                    formatted_date = str(raw_date).strip()

            # Safely parse booking count (in case there are commas like "1,200")
            raw_count = str(row.get('Booking Count', 0)).replace(',', '')
            try:
                booking_count = int(float(raw_count))
            except:
                booking_count = 0

            new_dept = UIDepartment(
                department=dept_name,
                primary_admin=str(row.get('Primary Admin', '')).strip(),
                primary_email=str(row.get('Primary Email', '')).strip(),
                primary_phone=str(row.get('Primary Phone', '')).strip() if not pd.isna(row.get('Primary Phone')) else '',
                secondary_admin=str(row.get('Secondary Admin', '')).strip() if not pd.isna(row.get('Secondary Admin')) else '',
                secondary_email=str(row.get('Secondary Email', '')).strip() if not pd.isna(row.get('Secondary Email')) else '',
                secondary_phone=str(row.get('Secondary Phone', '')).strip() if not pd.isna(row.get('Secondary Phone')) else '',
                booking_count=booking_count,
                last_booking_date=formatted_date
            )
            db.session.add(new_dept)
            count += 1
            
        db.session.commit()
        return jsonify({'message': f'Successfully synced {count} departments. Duplicates skipped.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    
@directory_bp.route('/api/save', methods=['POST'])
def save_department():
    data = request.json
    dept_id = data.get('id')
    
    try:
        if dept_id:
            dept = UIDepartment.query.get(dept_id)
            if not dept: return jsonify({'error': 'Department not found'}), 404
        else:
            if UIDepartment.query.filter_by(department=data['department']).first():
                return jsonify({'error': 'Department already exists.'}), 400
            dept = UIDepartment()
            db.session.add(dept)

        dept.department = data['department']
        dept.primary_admin = data['primary_admin']
        dept.primary_email = data['primary_email']
        dept.primary_phone = data.get('primary_phone', '')
        dept.secondary_admin = data.get('secondary_admin', '')
        dept.secondary_email = data.get('secondary_email', '')
        dept.secondary_phone = data.get('secondary_phone', '')
        dept.booking_count = int(data.get('booking_count', 0))
        dept.last_booking_date = data.get('last_booking_date', '')

        db.session.commit()
        return jsonify({'message': 'Department saved successfully.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500