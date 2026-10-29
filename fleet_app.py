import os
import pandas as pd
import sqlite3
from sqlalchemy import create_engine
from flask import Blueprint, render_template, request, jsonify
from werkzeug.utils import secure_filename

fleet_bp = Blueprint('fleet', __name__, url_prefix='/fleet')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_FILE = os.path.join(BASE_DIR, 'fleet_data.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
engine = create_engine(f'sqlite:///{DB_FILE}')

PRODUCT_COLUMN = 'New_Product_Category'
AVG_SPEED_MPH = 35
#FUEL_PRICE_PER_GALLON = 3.15
HIDDEN_CATEGORIES = {"Bus", "Motor Coach", "Wheel chair", "UNITED"}

HISTORICAL_FUEL_PRICES = {
    2017: 2.40,
    2018: 2.60,
    2019: 2.50,
    2020: 2.00,  # COVID dip
    2021: 2.90,
    2022: 3.80,  # Supply chain spike
    2023: 3.40,
    2024: 3.20,
    2025: 3.25,
    2026: 4.15,  # Updated to reflect current averages
}
DEFAULT_FUEL_PRICE = 3.15

VEHICLE_FLEET = {
    "Shuttle":     ["Chevrolet Suburban 2021", "Mercedes-Benz Sprinter Van 2021", "Ford Transit Van 2019", "GMC Terrain 2023"],
    "Private Car": ["Lincoln Continental 2020", "Chevrolet Suburban 2021", "Chevrolet Suburban 2018", "GMC Terrain 2023"],
    "Van":         ["Mercedes-Benz Sprinter Van 2021", "Ford Transit Van 2019"],
    "Limo":        ["Lincoln MKT Limo 2015"],
}

CATEGORY_DISPLAY_NAMES = {
    "Limo": "Limo Service", "Private Car": "Private Car Rides",
    "Shuttle": "Airport Shuttle", "Van": "Van Service",
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
        cursor.execute('''CREATE TABLE IF NOT EXISTS fleet_status (vehicle TEXT PRIMARY KEY, status TEXT)''')
        unique_vehicles = set()
        for vehicles in VEHICLE_FLEET.values(): unique_vehicles.update(vehicles)
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
            recalculate_costs() # Recalculate on startup
    except Exception:
        GLOBAL_DF = pd.DataFrame()

# ✅ NEW: ULTRA-FAST VECTORIZED CALCULATION
def recalculate_costs():
    global GLOBAL_DF
    if GLOBAL_DF.empty: return

    product_col = PRODUCT_COLUMN if PRODUCT_COLUMN in GLOBAL_DF.columns else 'Product_Category'
    GLOBAL_DF['normalized_cat'] = GLOBAL_DF[product_col].apply(normalize_category)

    cat_avg_mpg = {}
    for category, vehicles in VEHICLE_FLEET.items():
        available = [v for v in vehicles if fleet_status.get(v) == "Available"]
        cat_avg_mpg[category] = sum(VEHICLE_MPG[v] for v in available) / len(available) if available else None

    GLOBAL_DF['avg_mpg'] = GLOBAL_DF['normalized_cat'].map(cat_avg_mpg)
    GLOBAL_DF['driver_rate'] = GLOBAL_DF['normalized_cat'].map(DRIVER_HOURLY_RATES).fillna(0)
    GLOBAL_DF['fuel_price'] = GLOBAL_DF['Year'].map(HISTORICAL_FUEL_PRICES).fillna(DEFAULT_FUEL_PRICE)

    miles = GLOBAL_DF['Number of Hours'] * AVG_SPEED_MPH

    # ✅ NEW: Calculate Fuel Cost separately
    GLOBAL_DF['Fuel_Cost'] = (miles / GLOBAL_DF['avg_mpg']) * GLOBAL_DF['fuel_price']
    GLOBAL_DF.loc[GLOBAL_DF['avg_mpg'].isna(), 'Fuel_Cost'] = 0.0
    GLOBAL_DF['Fuel_Cost'] = GLOBAL_DF['Fuel_Cost'].fillna(0.0)

    # Total Cost = Fuel + Driver Wages
    GLOBAL_DF['Cost'] = GLOBAL_DF['Fuel_Cost'] + (GLOBAL_DF['Number of Hours'] * GLOBAL_DF['driver_rate'])
    GLOBAL_DF['Cost'] = GLOBAL_DF['Cost'].fillna(0.0)

def process_data(df):
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Year'] = df['Date'].dt.year # <--- Make sure this line is here
    df['Number of Hours'] = pd.to_numeric(df['Number of Hours'], errors='coerce').fillna(0)
    df['Miles'] = df['Number of Hours'] * AVG_SPEED_MPH
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
        GLOBAL_DF = df
        recalculate_costs()
        GLOBAL_DF.to_sql('rides', engine, if_exists='replace', index=False)
        return jsonify({'message': f'Dataset replaced. {len(df)} records loaded.', 'filters': get_filter_options()})
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@fleet_bp.route('/api/metrics')
def get_metrics():
    global GLOBAL_DF
    if GLOBAL_DF.empty: return jsonify({'error': 'No data loaded'}), 400

    df = GLOBAL_DF.copy()
    if 'Cancelled' in df.columns:
        df = df[df['Cancelled'].astype(str).str.strip().str.lower() != 'cancelled']

    year, month, product = request.args.get('year'), request.args.get('month'), request.args.get('product')

    if year and year != 'All': df = df[df['Year'] == int(year)]
    if month and month != 'All': df = df[df['Month'] == month]

    product_col = PRODUCT_COLUMN if PRODUCT_COLUMN in df.columns else 'Product_Category'
    if product and product != 'All': df = df[df[product_col] == product]

    # ✅ NEW: Calculate Average Fuel Cost
    avg_fuel_cost = df['Fuel_Cost'].mean() if not df.empty else 0.0

    return jsonify({
        'total_miles': f"{df['Miles'].sum():,.0f} mi",
        'total_hours': f"{df['Number of Hours'].sum():,.0f}",
        'avg_cost': f"${df['Cost'].mean():,.2f}" if not df.empty else "$0.00",
        'avg_fuel_cost': f"${avg_fuel_cost:,.2f}", # <--- Added here
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

    # Recalculate instantly in memory (Vectorized)
    if not GLOBAL_DF.empty:
        recalculate_costs()

    # ✅ FIX: Don't rewrite the whole DB on toggle.
    # The DB only needs to be updated when a new file is uploaded.
    # The UI calculates the new costs from memory instantly.

    return jsonify({'vehicle': vehicle, 'status': new_status})

# Initialize on import
init_db()
load_fleet_status()
load_rides_data()