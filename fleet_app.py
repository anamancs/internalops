import os
import re
import requests
from io import StringIO
import pandas as pd
import sqlite3
import calendar
from datetime import date, datetime
from sqlalchemy import create_engine
from flask import Blueprint, render_template, request, jsonify
from werkzeug.utils import secure_filename
from flask_login import login_required
from extensions import db  # ✅ MOVED THIS TO THE TOP


fleet_bp = Blueprint('fleet', __name__, url_prefix='/fleet')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_FILE = os.path.join(BASE_DIR, 'fleet_data.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
engine = create_engine(f'sqlite:///{DB_FILE}')

PRODUCT_COLUMN = 'New_Product_Category'
AVG_SPEED_MPH = 35
# Fleet-wide calibration calculated from March-September 2026: 173,365.52 GPS mi / 252,034 booking-estimated mi.
GPS_CORRECTION_FACTOR = 0.687866 

HIDDEN_CATEGORIES = {"Bus", "Motor Coach", "Wheel chair", "UNITED"}

VEHICLE_FLEET = {
    "Shuttle":     ["Chevrolet Suburban 2021", "Mercedes-Benz Sprinter Van 2021", "Ford Transit Van 2019", "GMC Terrain 2023"],
    "Private Car": ["Lincoln Continental 2020", "Chevrolet Suburban 2021", "Chevrolet Suburban 2018", "GMC Terrain 2023"],
    "Van":         ["Mercedes-Benz Sprinter Van 2021", "Ford Transit Van 2019"],
    "Limo":        ["Lincoln MKT Limo 2015"],
}

CATEGORY_DISPLAY_NAMES = {
    "Limo": "Limo Service", "Private Car": "Private Car", "Shuttle": "Shuttles", "Van": "Van Service",
}

VEHICLE_MPG = {
    "Chevrolet Suburban 2021": 18, "Mercedes-Benz Sprinter Van 2021": 18,
    "Ford Transit Van 2019": 18, "GMC Terrain 2023": 26,
    "Lincoln Continental 2020": 21, "Chevrolet Suburban 2018": 18,
    "Lincoln MKT Limo 2015": 16
}

DRIVER_HOURLY_RATES = {
    "Shuttle": 15.00, "Private Car": 15.00, "Van": 17.00, "Limo": 17.00,
}

CATEGORY_ALIASES = {
    "limoservice": "Limo", "vanservice": "Van", "privatecar": "Private Car", "shuttleservice": "Shuttle",
}
_CATEGORY_LOOKUP = {cat.strip().lower().replace(' ', ''): cat for cat in VEHICLE_FLEET.keys()}

# ✅ GPS Vehicle ID Mapping (Now includes the IDs in the name)
GPS_VEHICLE_MAP = {
    "01": "01 - Lincoln Continental 2020",
    "02": "02 - Chevrolet Suburban 2021",
    "03": "03 - Mercedes-Benz Sprinter Van 2021",
    "04": "04 - Ford Transit Van 2019",
    "05": "05 - Chevrolet Suburban 2018",
    "07 Wheelchair SUV": "07 - Wheelchair SUV",
    "09": "09 - GMC Terrain 2023",
    "ACS LIMO": "ACS LIMO - Lincoln MKT Limo 2015",
    "TEMSA TS45": "TEMSA TS45"
}

# Fuel type is assigned by physical vehicle, not by booking product category.
VEHICLE_FUEL_TYPES = {
    "Lincoln Continental 2020": "Gasoline",
    "Chevrolet Suburban 2021": "Gasoline",
    "Mercedes-Benz Sprinter Van 2021": "Diesel",
    "Ford Transit Van 2019": "Gasoline",
    "Chevrolet Suburban 2018": "Gasoline",
    "Wheelchair SUV": "Gasoline",
    "GMC Terrain 2023": "Gasoline",
    "Lincoln MKT Limo 2015": "Gasoline",
    "TEMSA TS45": "Diesel",
}

GPS_VEHICLE_FUEL_TYPES = {
    "01": "Gasoline",
    "02": "Gasoline",
    "03": "Diesel",
    "04": "Gasoline",
    "05": "Gasoline",
    "07 Wheelchair SUV": "Gasoline",
    "09": "Gasoline",
    "ACS LIMO": "Gasoline",
    "TEMSA TS45": "Diesel",
}

# Monthly retail prices, USD/gallon, for regular gasoline and No. 2 on-highway
# diesel. Source: EIA Midwest (PADD 2) monthly series. This is a regional proxy,
# not an Iowa City-only monthly average. Monthly values are used for 2017-2026.
# For years before 2017 or months not yet published, the project default is used.
DEFAULT_FUEL_PRICE = 3.15
MONTHLY_FUEL_PRICES = {
    # 2017
    (2017, 1): {"Gasoline": 2.272, "Diesel": 2.528},
    (2017, 2): {"Gasoline": 2.199, "Diesel": 2.493},
    (2017, 3): {"Gasoline": 2.222, "Diesel": 2.479},
    (2017, 4): {"Gasoline": 2.334, "Diesel": 2.516},
    (2017, 5): {"Gasoline": 2.281, "Diesel": 2.494},
    (2017, 6): {"Gasoline": 2.231, "Diesel": 2.439},
    (2017, 7): {"Gasoline": 2.207, "Diesel": 2.440},
    (2017, 8): {"Gasoline": 2.285, "Diesel": 2.562},
    (2017, 9): {"Gasoline": 2.473, "Diesel": 2.736},
    (2017, 10): {"Gasoline": 2.386, "Diesel": 2.766},
    (2017, 11): {"Gasoline": 2.498, "Diesel": 2.876},
    (2017, 12): {"Gasoline": 2.365, "Diesel": 2.862},
    # 2018
    (2018, 1): {"Gasoline": 2.473, "Diesel": 2.973},
    (2018, 2): {"Gasoline": 2.448, "Diesel": 2.995},
    (2018, 3): {"Gasoline": 2.469, "Diesel": 2.913},
    (2018, 4): {"Gasoline": 2.620, "Diesel": 3.013},
    (2018, 5): {"Gasoline": 2.803, "Diesel": 3.179},
    (2018, 6): {"Gasoline": 2.793, "Diesel": 3.185},
    (2018, 7): {"Gasoline": 2.769, "Diesel": 3.163},
    (2018, 8): {"Gasoline": 2.753, "Diesel": 3.143},
    (2018, 9): {"Gasoline": 2.755, "Diesel": 3.203},
    (2018, 10): {"Gasoline": 2.748, "Diesel": 3.325},
    (2018, 11): {"Gasoline": 2.462, "Diesel": 3.237},
    (2018, 12): {"Gasoline": 2.126, "Diesel": 3.010},
    # 2019
    (2019, 1): {"Gasoline": 2.035, "Diesel": 2.826},
    (2019, 2): {"Gasoline": 2.186, "Diesel": 2.890},
    (2019, 3): {"Gasoline": 2.442, "Diesel": 3.003},
    (2019, 4): {"Gasoline": 2.704, "Diesel": 3.017},
    (2019, 5): {"Gasoline": 2.740, "Diesel": 3.049},
    (2019, 6): {"Gasoline": 2.617, "Diesel": 2.978},
    (2019, 7): {"Gasoline": 2.682, "Diesel": 2.947},
    (2019, 8): {"Gasoline": 2.542, "Diesel": 2.914},
    (2019, 9): {"Gasoline": 2.486, "Diesel": 2.920},
    (2019, 10): {"Gasoline": 2.466, "Diesel": 2.964},
    (2019, 11): {"Gasoline": 2.423, "Diesel": 2.967},
    (2019, 12): {"Gasoline": 2.419, "Diesel": 2.973},
    # 2020
    (2020, 1): {"Gasoline": 2.409, "Diesel": 2.945},
    (2020, 2): {"Gasoline": 2.309, "Diesel": 2.782},
    (2020, 3): {"Gasoline": 2.036, "Diesel": 2.587},
    (2020, 4): {"Gasoline": 1.542, "Diesel": 2.340},
    (2020, 5): {"Gasoline": 1.748, "Diesel": 2.237},
    (2020, 6): {"Gasoline": 2.014, "Diesel": 2.262},
    (2020, 7): {"Gasoline": 2.098, "Diesel": 2.307},
    (2020, 8): {"Gasoline": 2.072, "Diesel": 2.310},
    (2020, 9): {"Gasoline": 2.047, "Diesel": 2.295},
    (2020, 10): {"Gasoline": 2.023, "Diesel": 2.266},
    (2020, 11): {"Gasoline": 1.957, "Diesel": 2.322},
    (2020, 12): {"Gasoline": 2.076, "Diesel": 2.514},
    # 2021
    (2021, 1): {"Gasoline": 2.231, "Diesel": 2.622},
    (2021, 2): {"Gasoline": 2.409, "Diesel": 2.805},
    (2021, 3): {"Gasoline": 2.724, "Diesel": 3.118},
    (2021, 4): {"Gasoline": 2.776, "Diesel": 3.064},
    (2021, 5): {"Gasoline": 2.882, "Diesel": 3.162},
    (2021, 6): {"Gasoline": 2.973, "Diesel": 3.231},
    (2021, 7): {"Gasoline": 3.035, "Diesel": 3.262},
    (2021, 8): {"Gasoline": 3.034, "Diesel": 3.253},
    (2021, 9): {"Gasoline": 3.044, "Diesel": 3.296},
    (2021, 10): {"Gasoline": 3.158, "Diesel": 3.554},
    (2021, 11): {"Gasoline": 3.211, "Diesel": 3.624},
    (2021, 12): {"Gasoline": 3.069, "Diesel": 3.505},
    # 2022
    (2022, 1): {"Gasoline": 3.112, "Diesel": 3.594},
    (2022, 2): {"Gasoline": 3.357, "Diesel": 3.891},
    (2022, 3): {"Gasoline": 4.024, "Diesel": 4.912},
    (2022, 4): {"Gasoline": 3.915, "Diesel": 4.936},
    (2022, 5): {"Gasoline": 4.260, "Diesel": 5.320},
    (2022, 6): {"Gasoline": 4.879, "Diesel": 5.662},
    (2022, 7): {"Gasoline": 4.496, "Diesel": 5.460},
    (2022, 8): {"Gasoline": 3.809, "Diesel": 5.000},
    (2022, 9): {"Gasoline": 3.590, "Diesel": 5.023},
    (2022, 10): {"Gasoline": 3.744, "Diesel": 5.226},
    (2022, 11): {"Gasoline": 3.587, "Diesel": 5.253},
    (2022, 12): {"Gasoline": 3.014, "Diesel": 4.609},
    # 2023
    (2023, 1): {"Gasoline": 3.217, "Diesel": 4.427},
    (2023, 2): {"Gasoline": 3.231, "Diesel": 4.242},
    (2023, 3): {"Gasoline": 3.270, "Diesel": 4.055},
    (2023, 4): {"Gasoline": 3.512, "Diesel": 3.983},
    (2023, 5): {"Gasoline": 3.454, "Diesel": 3.832},
    (2023, 6): {"Gasoline": 3.471, "Diesel": 3.731},
    (2023, 7): {"Gasoline": 3.436, "Diesel": 3.818},
    (2023, 8): {"Gasoline": 3.701, "Diesel": 4.300},
    (2023, 9): {"Gasoline": 3.666, "Diesel": 4.435},
    (2023, 10): {"Gasoline": 3.371, "Diesel": 4.425},
    (2023, 11): {"Gasoline": 3.138, "Diesel": 4.241},
    (2023, 12): {"Gasoline": 2.887, "Diesel": 3.882},
    # 2024
    (2024, 1): {"Gasoline": 2.829, "Diesel": 3.716},
    (2024, 2): {"Gasoline": 3.044, "Diesel": 3.938},
    (2024, 3): {"Gasoline": 3.318, "Diesel": 3.943},
    (2024, 4): {"Gasoline": 3.441, "Diesel": 3.948},
    (2024, 5): {"Gasoline": 3.430, "Diesel": 3.725},
    (2024, 6): {"Gasoline": 3.312, "Diesel": 3.597},
    (2024, 7): {"Gasoline": 3.411, "Diesel": 3.747},
    (2024, 8): {"Gasoline": 3.338, "Diesel": 3.678},
    (2024, 9): {"Gasoline": 3.091, "Diesel": 3.531},
    (2024, 10): {"Gasoline": 3.016, "Diesel": 3.588},
    (2024, 11): {"Gasoline": 2.888, "Diesel": 3.505},
    (2024, 12): {"Gasoline": 2.881, "Diesel": 3.463},
    # 2025
    (2025, 1): {"Gasoline": 2.942, "Diesel": 3.570},
    (2025, 2): {"Gasoline": 2.956, "Diesel": 3.592},
    (2025, 3): {"Gasoline": 2.954, "Diesel": 3.504},
    (2025, 4): {"Gasoline": 3.029, "Diesel": 3.505},
    (2025, 5): {"Gasoline": 3.013, "Diesel": 3.439},
    (2025, 6): {"Gasoline": 3.019, "Diesel": 3.569},
    (2025, 7): {"Gasoline": 3.004, "Diesel": 3.764},
    (2025, 8): {"Gasoline": 3.028, "Diesel": 3.735},
    (2025, 9): {"Gasoline": 3.012, "Diesel": 3.730},
    (2025, 10): {"Gasoline": 2.856, "Diesel": 3.639},
    (2025, 11): {"Gasoline": 2.876, "Diesel": 3.857},
    (2025, 12): {"Gasoline": 2.672, "Diesel": 3.573},
    # 2026
    (2026, 1): {"Gasoline": 2.633, "Diesel": 3.444},
    (2026, 2): {"Gasoline": 2.674, "Diesel": 3.681},
    (2026, 3): {"Gasoline": 3.371, "Diesel": 4.785},
    (2026, 4): {"Gasoline": 3.833, "Diesel": 5.246},
    (2026, 5): {"Gasoline": 4.389, "Diesel": 5.732},
    (2026, 6): {"Gasoline": 3.858, "Diesel": 4.984},
    (2026, 7): {"Gasoline": 3.714, "Diesel": 4.825},
    (2026, 8): {"Gasoline": 3.893, "Diesel": 5.417},
    (2026, 9): {"Gasoline": 4.166, "Diesel": 6.351},
    (2026, 10): {"Gasoline": 4.167, "Diesel": 6.344},
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]
MONTH_NUMBER = {
    key: number
    for number, name in enumerate(MONTH_NAMES, 1)
    for key in (name, name[:3])
}

def get_fuel_price(year, month, fuel_type):
    """Return the monthly fuel price when available, otherwise legacy fallback."""
    try:
        year = int(year)
        if isinstance(month, str):
            month = MONTH_NUMBER.get(month.strip().title(), month)
        month = int(month)
    except (TypeError, ValueError):
        month = None
        year = None

    monthly_prices = MONTHLY_FUEL_PRICES.get((year, month), {})
    if fuel_type in monthly_prices:
        return monthly_prices[fuel_type]
    return DEFAULT_FUEL_PRICE

def get_vehicle_fuel_type(vehicle_id):
    return GPS_VEHICLE_FUEL_TYPES.get(str(vehicle_id).strip())


def calculate_estimated_fuel_cost(start_date=None, end_date=None):
    """Calculate GPS-based estimated fuel cost for an optional date range.

    GPS records are stored by calendar month, so a month is included when it
    overlaps the requested date range. Vehicles without a mapped fuel type are
    excluded, matching the Fleet Dashboard calculation.
    """
    total = 0.0

    for log in GpsLog.query.all():
        try:
            year = int(log.year)
            month_value = log.month
            if isinstance(month_value, str):
                month_number = MONTH_NUMBER.get(month_value.strip().title())
                if month_number is None:
                    month_number = int(month_value)
            else:
                month_number = int(month_value)
            month_start = datetime(year, month_number, 1).date()
            month_end = date(year, month_number, calendar.monthrange(year, month_number)[1])
        except (TypeError, ValueError):
            continue

        if start_date and month_end < start_date:
            continue
        if end_date and month_start > end_date:
            continue

        fuel_type = get_vehicle_fuel_type(log.vehicle_id)
        if not fuel_type:
            continue

        fuel_price = get_fuel_price(year, month_number, fuel_type)
        gallons = float(log.idle_fuel or 0.0) + float(log.driving_fuel or 0.0)
        total += gallons * fuel_price

    return round(total, 2)


def category_fuel_cost_per_mile(category, year, month):
    """Estimate category fuel cost/mile using its eligible fleet mix.

    Vehicles may serve multiple product categories. Without trip-to-vehicle
    assignments, each eligible vehicle contributes equally to the category rate.
    """
    vehicles = VEHICLE_FLEET.get(category, [])
    rates = []
    for vehicle in vehicles:
        mpg = VEHICLE_MPG.get(vehicle)
        fuel_type = VEHICLE_FUEL_TYPES.get(vehicle)
        if mpg and fuel_type:
            rates.append(get_fuel_price(year, month, fuel_type) / mpg)
    return sum(rates) / len(rates) if rates else 0.0

def normalize_category(raw_value):
    if pd.isna(raw_value): return None
    key = str(raw_value).strip().lower().replace(' ', '')
    if key in _CATEGORY_LOOKUP: return _CATEGORY_LOOKUP[key]
    if key in CATEGORY_ALIASES: return CATEGORY_ALIASES[key]
    return None

fleet_status = {}
GLOBAL_DF = pd.DataFrame()

# --- Database Models ---
class GpsLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer)
    month = db.Column(db.String(20))
    vehicle_id = db.Column(db.String(50))
    vehicle_name = db.Column(db.String(100))
    utilization_pct = db.Column(db.Integer)
    idle_hours = db.Column(db.Float)
    driving_hours = db.Column(db.Float)
    idle_fuel = db.Column(db.Float)
    driving_fuel = db.Column(db.Float)
    distance = db.Column(db.Float)

# --- Helpers to Parse Go Motive Strings ---
def parse_time(time_str):
    if pd.isna(time_str) or '0 secs' in str(time_str): return 0.0
    hrs = re.search(r'(\d+)\s*hrs?', str(time_str))
    mins = re.search(r'(\d+)\s*mins?', str(time_str))
    secs = re.search(r'(\d+)\s*secs?', str(time_str))
    h = int(hrs.group(1)) if hrs else 0
    m = int(mins.group(1)) if mins else 0
    s = int(secs.group(1)) if secs else 0
    return h + (m/60) + (s/3600)

def parse_number(num_str):
    if pd.isna(num_str): return 0.0
    return float(str(num_str).replace(',', ''))

# --- Database Init & Logic ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS fleet_status (vehicle TEXT PRIMARY KEY, status TEXT)')
        unique_vehicles = set(v for v_list in VEHICLE_FLEET.values() for v in v_list)
        for v in unique_vehicles:
            cursor.execute('INSERT OR IGNORE INTO fleet_status (vehicle, status) VALUES (?, ?)', (v, 'Available'))
        conn.commit()

def load_fleet_status():
    global fleet_status
    with sqlite3.connect(DB_FILE) as conn:
        df = pd.read_sql_query("SELECT vehicle, status FROM fleet_status", conn)
        fleet_status = dict(zip(df['vehicle'], df['status']))

def load_rides_data():
    global GLOBAL_DF
    try:
        GLOBAL_DF = pd.read_sql_query("SELECT * FROM rides", engine)
        if not GLOBAL_DF.empty:
            GLOBAL_DF['Date'] = pd.to_datetime(GLOBAL_DF['Date'], errors='coerce')
            recalculate_costs()
    except:
        GLOBAL_DF = pd.DataFrame()

def recalculate_costs():
    global GLOBAL_DF
    if GLOBAL_DF.empty:
        return

    product_col = PRODUCT_COLUMN if PRODUCT_COLUMN in GLOBAL_DF.columns else 'Product_Category'
    GLOBAL_DF['normalized_cat'] = GLOBAL_DF[product_col].apply(normalize_category)

    # Historical costs must not change when today's fleet availability is toggled.
    cat_avg_mpg = {
        category: (sum(VEHICLE_MPG[v] for v in vehicles if v in VEHICLE_MPG) /
                   len([v for v in vehicles if v in VEHICLE_MPG]))
        for category, vehicles in VEHICLE_FLEET.items()
    }
    GLOBAL_DF['avg_mpg'] = GLOBAL_DF['normalized_cat'].map(cat_avg_mpg)
    GLOBAL_DF['driver_rate'] = GLOBAL_DF['normalized_cat'].map(DRIVER_HOURLY_RATES).fillna(0)

    if 'Date' in GLOBAL_DF.columns:
        ride_dates = pd.to_datetime(GLOBAL_DF['Date'], errors='coerce')
        years = ride_dates.dt.year
        months = ride_dates.dt.month
    else:
        years = pd.to_numeric(GLOBAL_DF.get('Year'), errors='coerce')
        months = pd.Series([None] * len(GLOBAL_DF), index=GLOBAL_DF.index)

    raw_miles = pd.to_numeric(GLOBAL_DF['Number of Hours'], errors='coerce').fillna(0) * AVG_SPEED_MPH
    GLOBAL_DF['Miles'] = raw_miles * GPS_CORRECTION_FACTOR

    # Product categories can use multiple physical vehicle types. Estimate fuel
    # cost/mile from the eligible category fleet mix and that month's fuel prices.
    GLOBAL_DF['fuel_cost_per_mile'] = [
        category_fuel_cost_per_mile(cat, year, month)
        for cat, year, month in zip(GLOBAL_DF['normalized_cat'], years, months)
    ]
    GLOBAL_DF['Fuel_Cost'] = GLOBAL_DF['Miles'] * GLOBAL_DF['fuel_cost_per_mile']
    GLOBAL_DF['Cost'] = GLOBAL_DF['Fuel_Cost'].fillna(0.0) + (
        pd.to_numeric(GLOBAL_DF['Number of Hours'], errors='coerce').fillna(0) * GLOBAL_DF['driver_rate']
    )

def process_data(df):
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Year'] = df['Date'].dt.year
    df['Number of Hours'] = pd.to_numeric(df['Number of Hours'], errors='coerce').fillna(0)
    return df

def get_filter_options():
    global GLOBAL_DF
    if GLOBAL_DF.empty: return {'years': [], 'months': [], 'products': []}
    years = sorted(GLOBAL_DF['Year'].dropna().astype(int).unique().tolist())
    month_order = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
    present_months = GLOBAL_DF['Month'].dropna().unique().tolist()
    months = [m for m in month_order if m in present_months]
    product_col = PRODUCT_COLUMN if PRODUCT_COLUMN in GLOBAL_DF.columns else 'Product_Category'
    raw_products = sorted(GLOBAL_DF[product_col].dropna().unique().tolist())
    raw_products = [p for p in raw_products if p not in HIDDEN_CATEGORIES]
    products = [{'value': p, 'label': CATEGORY_DISPLAY_NAMES.get(p, p)} for p in raw_products]
    return {'years': years, 'months': months, 'products': products}

# --- Routes ---
@fleet_bp.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html')

@fleet_bp.route('/api/filters')
@login_required
def api_filters():
    return jsonify({'filters': get_filter_options(), 'has_data': not GLOBAL_DF.empty, 'record_count': len(GLOBAL_DF)})

@fleet_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    global GLOBAL_DF
    file = request.files.get('file')
    if not file: return jsonify({'error': 'No file'}), 400
    filepath = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    file.save(filepath)
    try:
        df = pd.read_csv(filepath) if filepath.endswith('.csv') else pd.read_excel(filepath)
        df = process_data(df)
        GLOBAL_DF = df
        recalculate_costs()
        GLOBAL_DF.to_sql('rides', engine, if_exists='replace', index=False)
        return jsonify({'message': f'Dataset replaced. {len(df)} records loaded.', 'filters': get_filter_options()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fleet_bp.route('/upload_gps', methods=['POST'])
@login_required
def upload_gps():
    file = request.files.get('file')
    year = request.form.get('year')
    month = request.form.get('month')
    if not file or not year or not month: return jsonify({'error': 'Missing data'}), 400
    
    filepath = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    file.save(filepath)
    
    try:
        df = pd.read_csv(filepath, sep='\t') if filepath.endswith('.csv') else pd.read_excel(filepath)
        df.columns = [c.strip() for c in df.columns]
        
        # ✅ FIXED: Use SQLAlchemy to delete old records
        GpsLog.query.filter_by(year=int(year), month=month).delete()
        db.session.commit()

        count = 0
        for _, row in df.iterrows():
            v_id = str(row.get('Vehicle')).strip()
            v_name = GPS_VEHICLE_MAP.get(v_id, v_id)
            
            new_log = GpsLog(
                year=int(year),
                month=month,
                vehicle_id=v_id,
                vehicle_name=v_name,
                utilization_pct=int(parse_number(row.get('Utilization (percentage)', 0))),
                idle_hours=parse_time(row.get('Idling Time (formatted)')), # Ensure exact column name
                driving_hours=parse_time(row.get('Driving Time (formatted)')), # Ensure exact column name
                idle_fuel=parse_number(row.get('Idled Fuel (measured)')), # Ensure exact column name
                driving_fuel=parse_number(row.get('Driving Fuel')),
                distance=parse_number(row.get('Distance'))
            )
            db.session.add(new_log)
            count += 1
        db.session.commit()
        return jsonify({'message': f'GPS data for {month} {year} synced. {count} vehicles updated.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@fleet_bp.route('/sync_gps_sheet', methods=['POST'])
@login_required
def sync_gps_sheet():
    sheet_url = os.environ.get("GOOGLE_GPS_SHEET_URL")
    if not sheet_url:
        return jsonify({'error': 'GOOGLE_GPS_SHEET_URL not configured in .env'}), 500

    try:
        response = requests.get(sheet_url)
        response.raise_for_status()
        
        df = pd.read_csv(StringIO(response.text))
        df.columns = [c.strip() for c in df.columns]
        
        required_cols = ['Year', 'Month', 'Vehicle', 'Utilization (percentage)', 'Idling Time (formatted)', 
                         'Driving Time (formatted)', 'Idled Fuel (measured)', 'Driving Fuel', 'Distance']
        if not all(col in df.columns for col in required_cols):
            return jsonify({'error': f'Missing columns. Ensure the sheet has: {", ".join(required_cols)}'}), 400

        # ✅ FIXED: Use SQLAlchemy to delete old records
        unique_periods = df[['Year', 'Month']].drop_duplicates()
        for _, row in unique_periods.iterrows():
            GpsLog.query.filter_by(year=int(row['Year']), month=str(row['Month']).strip()).delete()
        db.session.commit()

        count = 0
        for _, row in df.iterrows():
            if pd.isna(row['Vehicle']): continue
            
            v_id = str(row['Vehicle']).strip()
            v_name = GPS_VEHICLE_MAP.get(v_id, v_id)
            
            new_log = GpsLog(
                year=int(row['Year']),
                month=str(row['Month']).strip(),
                vehicle_id=v_id,
                vehicle_name=v_name,
                utilization_pct=int(parse_number(row['Utilization (percentage)'])),
                idle_hours=parse_time(row['Idling Time (formatted)']),
                driving_hours=parse_time(row['Driving Time (formatted)']),
                idle_fuel=parse_number(row['Idled Fuel (measured)']),
                driving_fuel=parse_number(row['Driving Fuel']),
                distance=parse_number(row['Distance'])
            )
            db.session.add(new_log)
            count += 1
            
        db.session.commit()
        return jsonify({'message': f'Successfully synced {count} GPS records from Google Sheets.'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Sync failed: {str(e)}'}), 500


@fleet_bp.route('/api/metrics')
@login_required
def get_metrics():
    global GLOBAL_DF
    if GLOBAL_DF.empty: return jsonify({'error': 'No data'}), 400
    df = GLOBAL_DF.copy()
    year, month, product = request.args.get('year'), request.args.get('month'), request.args.get('product')

    if year and year != 'All': df = df[df['Year'] == int(year)]
    if month and month != 'All': df = df[df['Month'] == month]
    product_col = PRODUCT_COLUMN if PRODUCT_COLUMN in df.columns else 'Product_Category'
    if product and product != 'All': df = df[df[product_col] == product]

    # ✅ Build data for the new Chart.js Bar Chart
    breakdown = {}
    if not df.empty:
        for cat in df['normalized_cat'].dropna().unique():
            cat_df = df[df['normalized_cat'] == cat]
            breakdown[cat] = round(cat_df['Cost'].mean(), 2)

    avg_fuel_cost = df['Fuel_Cost'].mean() if not df.empty else 0.0
    return jsonify({
        'total_miles': f"{df['Miles'].sum():,.0f} mi",
        'total_hours': f"{df['Number of Hours'].sum():,.0f}",
        'avg_cost': f"${df['Cost'].mean():,.2f}" if not df.empty else "$0.00",
        'avg_fuel_cost': f"${avg_fuel_cost:,.2f}",
        'run_count': len(df),
        'cost_breakdown': breakdown
    })

@fleet_bp.route('/api/gps_metrics')
@login_required
def get_gps_metrics():
    year = request.args.get('year')
    month = request.args.get('month')

    query = GpsLog.query
    if year and year != 'All':
        query = query.filter_by(year=int(year))
    if month and month != 'All':
        query = query.filter_by(month=month)

    logs = query.all()
    if not logs:
        return jsonify({'error': 'No GPS data found for the selected period.'}), 404

    vehicle_data = {}
    total_idle_cost = 0.0
    total_drive_cost = 0.0
    total_gallons = 0.0
    total_fuel_cost = 0.0
    applied_prices = {}
    unmapped_vehicles = set()

    for log in logs:
        vid = str(log.vehicle_id).strip()
        fuel_type = get_vehicle_fuel_type(vid)
        if not fuel_type:
            unmapped_vehicles.add(vid)
        fuel_price = get_fuel_price(log.year, log.month, fuel_type) if fuel_type else None
        idle_cost = (log.idle_fuel or 0.0) * fuel_price if fuel_price is not None else 0.0
        drive_cost = (log.driving_fuel or 0.0) * fuel_price if fuel_price is not None else 0.0
        gallons = (log.idle_fuel or 0.0) + (log.driving_fuel or 0.0)

        if vid not in vehicle_data:
            vehicle_data[vid] = {
                'id': vid, 'vehicle': log.vehicle_name, 'fuel_type': fuel_type or 'Unmapped',
                'utilization': 0, 'idle_hours': 0.0, 'drive_hours': 0.0,
                'idle_fuel': 0.0, 'drive_fuel': 0.0, 'distance': 0.0,
                'idle_cost': 0.0, 'drive_cost': 0.0, 'count': 0
            }
        v = vehicle_data[vid]
        v['idle_hours'] += log.idle_hours or 0.0
        v['drive_hours'] += log.driving_hours or 0.0
        v['idle_fuel'] += log.idle_fuel or 0.0
        v['drive_fuel'] += log.driving_fuel or 0.0
        v['distance'] += log.distance or 0.0
        v['idle_cost'] += idle_cost
        v['drive_cost'] += drive_cost
        v['utilization'] += log.utilization_pct or 0
        v['count'] += 1

        total_idle_cost += idle_cost
        total_drive_cost += drive_cost
        if fuel_price is not None:
            total_gallons += gallons
            total_fuel_cost += idle_cost + drive_cost
            applied_prices[f"{log.year}-{str(log.month)[:3]}-{fuel_type}"] = fuel_price

    results = []
    for v in vehicle_data.values():
        avg_util = v['utilization'] / v['count'] if v['count'] else 0
        results.append({
            'id': v['id'], 'vehicle': v['vehicle'], 'fuel_type': v['fuel_type'],
            'utilization': round(avg_util),
            'idle_hours': f"{v['idle_hours']:.1f}",
            'drive_hours': f"{v['drive_hours']:.1f}",
            'idle_fuel': f"{v['idle_fuel']:.2f}",
            'drive_fuel': f"{v['drive_fuel']:.2f}",
            'idle_cost': f"${v['idle_cost']:,.2f}",
            'drive_cost': f"${v['drive_cost']:,.2f}",
            'distance': f"{v['distance']:,.0f} mi"
        })

    weighted_price = total_fuel_cost / total_gallons if total_gallons else 0.0
    return jsonify({
        'fuel_price': f"${weighted_price:.2f} avg/gal" if total_gallons else 'N/A',
        'fuel_price_basis': 'Monthly price by vehicle fuel type',
        'fuel_prices_applied': applied_prices,
        'unmapped_fuel_vehicles': sorted(unmapped_vehicles),
        'total_idle_cost': f"${total_idle_cost:,.2f}",
        'total_drive_cost': f"${total_drive_cost:,.2f}",
        'total_fuel_cost': round(total_fuel_cost, 2),
        'fleet_data': results
    })

@fleet_bp.route('/api/fleet', methods=['GET'])
@login_required
def get_fleet():
    return jsonify({cat: [{'vehicle': v, 'status': fleet_status.get(v, 'Available')} for v in vehicles] for cat, vehicles in VEHICLE_FLEET.items()})

@fleet_bp.route('/api/fleet/toggle', methods=['POST'])
@login_required
def toggle_fleet():
    global GLOBAL_DF
    vehicle = request.json.get('vehicle')
    if vehicle not in fleet_status: return jsonify({'error': 'Not found'}), 404

    new_status = "Out of Commission" if fleet_status[vehicle] == "Available" else "Available"
    fleet_status[vehicle] = new_status

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('UPDATE fleet_status SET status = ? WHERE vehicle = ?', (new_status, vehicle))
        conn.commit()

    if not GLOBAL_DF.empty:
        recalculate_costs()
    return jsonify({'vehicle': vehicle, 'status': new_status})

# Add this route to fleet_app.py

@fleet_bp.route('/api/vehicle_history/<vehicle_id>', methods=['GET'])
@login_required
def get_vehicle_history(vehicle_id):
    logs = GpsLog.query.filter_by(vehicle_id=vehicle_id).all()
    if not logs:
        return jsonify({'error': 'No historical data found for this vehicle.'}), 404

    month_number = MONTH_NUMBER
    logs.sort(key=lambda log: (
        log.year,
        month_number.get(str(log.month).strip().title(), 0),
        log.id
    ))

    fuel_type = get_vehicle_fuel_type(vehicle_id)
    results = []
    for log in logs:
        fuel_price = get_fuel_price(log.year, log.month, fuel_type) if fuel_type else None
        results.append({
            'period': f"{log.month[:3]} {log.year}",
            'fuel_type': fuel_type or 'Unmapped',
            'fuel_price': fuel_price,
            'idle_fuel': log.idle_fuel,
            'drive_fuel': log.driving_fuel,
            'idle_cost': (log.idle_fuel * fuel_price) if fuel_price is not None else None,
            'drive_cost': (log.driving_fuel * fuel_price) if fuel_price is not None else None,
            'total_distance': log.distance
        })

    return jsonify({
        'vehicle_name': logs[0].vehicle_name,
        'fuel_type': fuel_type or 'Unmapped',
        'history': results
    })

# Init on import
init_db()
load_fleet_status()
load_rides_data()