import os
import pandas as pd
import sqlite3
from sqlalchemy import create_engine
from flask import Blueprint, render_template, request, jsonify
from werkzeug.utils import secure_filename

# Create the blueprint
fleet_bp = Blueprint('fleet', __name__, url_prefix='/fleet')

# --- CONFIG ---
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_FILE = 'fleet_data.db'
engine = create_engine(f'sqlite:///{DB_FILE}')

PRODUCT_COLUMN = 'New_Product_Category'
AVG_SPEED_MPH = 35
FUEL_PRICE_PER_GALLON = 3.15

HIDDEN_CATEGORIES = {"Bus", "Motor Coach", "Wheel chair", "UNITED"}

VEHICLE_FLEET = {
    "Shuttle":     ["02-Chevrolet Suburban 2021", "03-Mercedes-Benz Sprinter Van 2021", "04-Ford Transit Van 2019", "09-GMC Terrain 2023"],
    "Private Car": ["01-Lincoln Continental 2020", "02-Chevrolet Suburban 2021", "05-Chevrolet Suburban 2018", "09-GMC Terrain 2023"],
    "Van":         ["03-Mercedes-Benz Sprinter Van 2021", "04-Ford Transit Van 2019"],
    "Limo":        ["Lincoln MKT Limo 2015"],
}

CATEGORY_DISPLAY_NAMES = {
    "Limo":        "Limo Service",
    "Private Car": "Private Car",
    "Shuttle":     "Shuttles",
    "Van":         "Van Service",
}

VEHICLE_MPG = {
    "02-Chevrolet Suburban 2021": 18, "03-Mercedes-Benz Sprinter Van 2021": 18,
    "04-Ford Transit Van 2019": 18, "09-GMC Terrain 2023": 26,
    "01-Lincoln Continental 2020": 21, "05-Chevrolet Suburban 2018": 18,
    "Lincoln MKT Limo 2015": 16
}

DRIVER_HOURLY_RATES = {
    "Shuttle": 15.00, "Private Car": 15.00, "Van": 17.00, "Limo": 17.00,
}

CATEGORY_ALIASES = {
    "limoservice": "Limo", "vanservice": "Van", "privatecar": "Private Car", "shuttleservice": "Shuttle",
}

_CATEGORY_LOOKUP = {cat.strip().lower().replace(' ', ''): cat for cat in VEHICLE_FLEET.keys()}

def normalize_category(raw_value):
    if pd.isna(raw_value): return None
    key = str(raw_value).strip().lower().replace(' ', '')
    if key in _CATEGORY_LOOKUP: return _CATEGORY_LOOKUP[key]
    if key in CATEGORY_ALIASES: return CATEGORY_ALIASES[key]
    return None

fleet_status = {}
GLOBAL_DF = pd.DataFrame()

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fleet_status (
                vehicle TEXT PRIMARY KEY,
                status TEXT
            )
        ''')
        cursor.execute('SELECT COUNT(*) FROM fleet_status')
        if cursor.fetchone()[0] == 0:
            unique_vehicles = set()
            for vehicles in VEHICLE_FLEET.values(): unique_vehicles.update(vehicles)
            for v in unique_vehicles:
                cursor.execute('INSERT INTO fleet_status (vehicle, status) VALUES (?, ?)', (v, 'Available'))
        conn.commit()

def load_fleet_status():
    global fleet_status
    with sqlite3.connect(DB_FILE) as conn:
        df = pd.read_sql_query("SELECT vehicle, status FROM fleet_status", conn)
        fleet_status = dict(zip(df['vehicle'], df['status']))

def load_rides_data():
    global GLOBAL_DF
    try:
        df = pd.read_sql_query("SELECT * FROM rides", engine)
        if not df.empty:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            df['Cost'] = df.apply(calculate_ride_cost, axis=1)
            GLOBAL_DF = df
    except Exception:
        GLOBAL_DF = pd.DataFrame()

def calculate_ride_cost(row):
    hours = row.get('Number of Hours', 0)
    raw_category = row.get(PRODUCT_COLUMN, row.get('New_Product_Category', ''))
    category = normalize_category(raw_category)
    if category is None: return 0.0

    miles = hours * AVG_SPEED_MPH
    available_vehicles = [v for v in VEHICLE_FLEET.get(category, []) if fleet_status.get(v) == "Available"]
    
    fuel_cost = 0.0
    if available_vehicles:
        avg_mpg = sum(VEHICLE_MPG[v] for v in available_vehicles) / len(available_vehicles)
        fuel_cost = (miles / avg_mpg) * FUEL_PRICE_PER_GALLON

        # If no vehicles are available, we can't fulfill the ride. Cost = 0.
    if not available_vehicles:
        return 0.0


    driver_cost = hours * DRIVER_HOURLY_RATES.get(category, 0.0)
    return fuel_cost + driver_cost

def process_data(df):
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Year'] = df['Date'].dt.year
    df['Number of Hours'] = pd.to_numeric(df['Number of Hours'], errors='coerce').fillna(0)
    df['Miles'] = df['Number of Hours'] * AVG_SPEED_MPH
    df['Cost'] = df.apply(calculate_ride_cost, axis=1)
    return df

def get_filter_options():
    global GLOBAL_DF
    if GLOBAL_DF.empty: return {'years': [], 'months': [], 'products': []}
    years = sorted(GLOBAL_DF['Year'].dropna().astype(int).unique().tolist())
    month_order = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
    present_months = GLOBAL_DF['Month'].dropna().unique().tolist()
    months = [m for m in month_order if m in present_months]

    product_col = PRODUCT_COLUMN if PRODUCT_COLUMN in GLOBAL_DF.columns else 'New_Product_Category'
    raw_products = sorted(GLOBAL_DF[product_col].dropna().unique().tolist())
    raw_products = [p for p in raw_products if p not in HIDDEN_CATEGORIES]
    products = [{'value': p, 'label': CATEGORY_DISPLAY_NAMES.get(p, p)} for p in raw_products]
    return {'years': years, 'months': months, 'products': products}

# --- ROUTES (Notice they are @fleet_bp.route now) ---

@fleet_bp.route('/')
def dashboard():
    return render_template('dashboard.html')

@fleet_bp.route('/api/filters')
def api_filters():
    return jsonify({'filters': get_filter_options(), 'has_data': not GLOBAL_DF.empty, 'record_count': len(GLOBAL_DF)})

@fleet_bp.route('/upload', methods=['POST'])
def upload_file():
    global GLOBAL_DF
    if 'file' not in request.files: return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({'error': 'No selected file'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    try:
        df = pd.read_csv(filepath) if filename.endswith('.csv') else pd.read_excel(filepath)
        df = process_data(df)
        df.to_sql('rides', engine, if_exists='replace', index=False)
        GLOBAL_DF = df
        return jsonify({'message': f'Dataset replaced. {len(df)} records loaded.', 'filters': get_filter_options()})
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@fleet_bp.route('/api/metrics')
def get_metrics():
    global GLOBAL_DF
    if GLOBAL_DF.empty: return jsonify({'error': 'No data loaded'}), 400

    df = GLOBAL_DF.copy()
    year, month, product = request.args.get('year'), request.args.get('month'), request.args.get('product')

    if year and year != 'All': df = df[df['Year'] == int(year)]
    if month and month != 'All': df = df[df['Month'] == month]
    
    product_col = PRODUCT_COLUMN if PRODUCT_COLUMN in df.columns else 'New_Product_Category'
    if product and product != 'All': df = df[df[product_col] == product]

    return jsonify({
        'total_miles': f"{df['Miles'].sum():,.0f} mi",
        'total_hours': f"{df['Number of Hours'].sum():,.0f}",
        'avg_cost': f"${df['Cost'].mean():,.2f}" if not df.empty else "$0.00",
        'run_count': len(df)
    })

@fleet_bp.route('/api/fleet', methods=['GET'])
def get_fleet():
    fleet_data = {}
    for category, vehicles in VEHICLE_FLEET.items():
        fleet_data[category] = [{'vehicle': v, 'status': fleet_status.get(v, 'Available')} for v in vehicles]
    return jsonify(fleet_data)

@fleet_bp.route('/api/fleet/toggle', methods=['POST'])
def toggle_fleet():
    global GLOBAL_DF
    data = request.json
    vehicle = data.get('vehicle')
    if vehicle not in fleet_status: return jsonify({'error': 'Vehicle not found'}), 404

    new_status = "Out of Commission" if fleet_status[vehicle] == "Available" else "Available"
    fleet_status[vehicle] = new_status

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('UPDATE fleet_status SET status = ? WHERE vehicle = ?', (new_status, vehicle))
        conn.commit()

    if not GLOBAL_DF.empty:
        GLOBAL_DF['Cost'] = GLOBAL_DF.apply(calculate_ride_cost, axis=1)
        GLOBAL_DF.to_sql('rides', engine, if_exists='replace', index=False)

    return jsonify({'vehicle': vehicle, 'status': new_status})

# Initialize the database when this file is imported
init_db()
load_fleet_status()
load_rides_data()