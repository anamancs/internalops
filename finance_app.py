import requests
import os
import pandas as pd
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required
from werkzeug.utils import secure_filename
from extensions import db
from receipt_app import Receipt # Import the Receipt model to calculate driver expenses
from datetime import datetime, timedelta
import calendar

finance_bp = Blueprint('finance', __name__, url_prefix='/finance')


def _parse_finance_date(value):
    """Convert a database or receipt date into a date object."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return value

    value = str(value).strip()

    for date_format in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(value[:19], date_format).date()
        except ValueError:
            continue

    try:
        return pd.to_datetime(value, errors="raise").date()
    except Exception:
        return None


def _date_matches_period(value, period, today=None):
    """Apply the dashboard's selected date filter."""
    today = today or datetime.now().date()
    tx_date = _parse_finance_date(value)

    # Do not include unrecognizable dates in a restricted period.
    if tx_date is None:
        return period == "all"

    if period == "this_month":
        return (
            tx_date.month == today.month
            and tx_date.year == today.year
        )

    if period == "last_month":
        first_day_this_month = today.replace(day=1)
        last_month = first_day_this_month - timedelta(days=1)

        return (
            tx_date.month == last_month.month
            and tx_date.year == last_month.year
        )

    if period == "this_year":
        return tx_date.year == today.year

    return True


def _format_ledger_date(value):
    """Return dates in a consistent format for the ledger."""
    parsed = _parse_finance_date(value)
    return parsed.isoformat() if parsed else str(value or "")


@finance_bp.route('/sync', methods=['POST'])
@login_required
def sync_sheet():
    sheet_url = os.environ.get("GOOGLE_SHEET_URL")
    if not sheet_url:
        return jsonify({'error': 'GOOGLE_SHEET_URL not configured in .env'}), 500

    try:
        # 1. Fetch the CSV directly from Google
        response = requests.get(sheet_url)
        response.raise_for_status()
        
        # 2. Load it into Pandas
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        
        # Standardize column names
        df.columns = [c.strip().capitalize() for c in df.columns]
        
        # 3. Clear out old Google Sheet data to prevent duplicates
        # We use a special description marker to know which ones came from the sheet
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
        df = df.dropna(subset=['Date']) # Drop rows where the date couldn't be read
        Transaction.query.filter_by(description='Google Sheet Sync').delete()
        
        # 4. Insert new data
        count = 0
        for _, row in df.iterrows():
            if pd.isna(row['Amount']) or pd.isna(row['Type']): continue
            
            new_tx = Transaction(
                date=str(row['Date']),
                type=str(row['Type']).capitalize(),
                category=str(row['Category']),
                amount=float(row['Amount']),
                description='Google Sheet Sync' # Marker for easy cleanup
            )
            db.session.add(new_tx)
            count += 1
            
        db.session.commit()
        return jsonify({'message': f'Successfully synced {count} rows from Google Sheets.'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Sync failed: {str(e)}'}), 500

    
# --- Database Model ---
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(20), nullable=False) # 'Revenue' or 'Expense'
    category = db.Column(db.String(50), nullable=False) # e.g., 'Square Sales', 'Payroll', 'Loans'
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200))

# --- Routes ---
@finance_bp.route('/')
@login_required
def dashboard():
    return render_template('finance.html')


@finance_bp.route('/api/summary')
@login_required
def summary():
    period = request.args.get('period', 'all')
    today = datetime.now().date()

    # Match the selected Finance period to the monthly GPS records used by
    # the Fleet Dashboard. This is an operational estimate, not an accounting
    # expense, and is intentionally excluded from total_expenses/net_profit.
    if period == 'this_month':
        fuel_start = today.replace(day=1)
        fuel_end = today
    elif period == 'last_month':
        fuel_end = today.replace(day=1) - timedelta(days=1)
        fuel_start = fuel_end.replace(day=1)
    elif period == 'this_year':
        fuel_start = today.replace(month=1, day=1)
        fuel_end = today
    else:
        fuel_start = None
        fuel_end = None

    from fleet_app import calculate_estimated_fuel_cost
    estimated_fuel_expense = calculate_estimated_fuel_cost(fuel_start, fuel_end)

    transactions = Transaction.query.all()

    driver_receipts = Receipt.query.filter(
        Receipt.status.in_(['Approved', 'Paid'])
    ).all()

    filtered_txs = [
        tx for tx in transactions
        if _date_matches_period(tx.date, period, today)
    ]

    filtered_receipts = [
        receipt for receipt in driver_receipts
        if _date_matches_period(receipt.date, period, today)
    ]

    # Revenue and manually recorded expenses
    revenue = sum(
        float(tx.amount or 0)
        for tx in filtered_txs
        if tx.type == 'Revenue'
    )

    manual_expenses = sum(
        float(tx.amount or 0)
        for tx in filtered_txs
        if tx.type == 'Expense'
    )

    # Actual fuel purchases are recorded in the Google Sheet as an Expense
    # with the category "Actual Fuel Expense". They remain part of expenses.
    # Actual fuel purchases from Google Sheets / manual transactions
    sheet_fuel_expense = sum(
        float(tx.amount or 0)
        for tx in filtered_txs
        if tx.type == 'Expense'
        and (tx.category or '').strip().casefold() == 'actual fuel expense'
    )

    # Approved and paid driver Fuel claims
    driver_fuel_expense = sum(
        float(receipt.amount or 0)
        for receipt in filtered_receipts
        if (receipt.category or '').strip().casefold() == 'fuel'
    )

    # Combined actual fuel expense
    actual_fuel_expense = sheet_fuel_expense + driver_fuel_expense

    fuel_variance = actual_fuel_expense - estimated_fuel_expense
    fuel_variance_pct = (
        fuel_variance / estimated_fuel_expense * 100
        if estimated_fuel_expense > 0 else 0.0
    )

    # Approved and paid driver reimbursements
    receipt_expenses = sum(
        float(receipt.amount or 0)
        for receipt in filtered_receipts
    )

    total_expenses = manual_expenses + receipt_expenses
    net_profit = revenue - total_expenses
    margin = (net_profit / revenue * 100) if revenue > 0 else 0.0

    # Dynamic expense categories / cost centers
    expense_breakdown = {}

    for tx in filtered_txs:
        if tx.type == 'Expense':
            category = (tx.category or 'Uncategorized').strip()

            expense_breakdown[category] = (
                expense_breakdown.get(category, 0)
                + float(tx.amount or 0)
            )

    # Preserve the original category of every driver reimbursement
    for receipt in filtered_receipts:
        category = (receipt.category or 'Uncategorized').strip().title()

        finance_category = f"Driver Reimbursements – {category}"

        expense_breakdown[finance_category] = (
            expense_breakdown.get(finance_category, 0)
            + float(receipt.amount or 0)
        )

    # Sort categories from highest spending to lowest
    expense_categories = [
        {
            'category': category,
            'amount': round(amount, 2),
            'percentage': round(
                (amount / total_expenses * 100), 1
            ) if total_expenses > 0 else 0
        }
        for category, amount in sorted(
            expense_breakdown.items(),
            key=lambda item: item[1],
            reverse=True
        )
    ]

    return jsonify({
        'revenue': f"${revenue:,.2f}",
        'total_expenses': f"${total_expenses:,.2f}",
        'net_profit': f"${net_profit:,.2f}",
        'margin': f"{margin:.1f}%",
        'is_profitable': net_profit >= 0,
        'estimated_fuel_expense': round(estimated_fuel_expense, 2),
        'actual_fuel_expense': round(actual_fuel_expense, 2),
        'fuel_variance': round(fuel_variance, 2),
        'fuel_variance_pct': round(fuel_variance_pct, 1),
        'expense_breakdown': expense_breakdown,
        'expense_categories': expense_categories,
        'transaction_counts': {
            'revenue': sum(
                1 for tx in filtered_txs if tx.type == 'Revenue'
            ),
            'expenses': sum(
                1 for tx in filtered_txs if tx.type == 'Expense'
            ),
            'driver_reimbursements': len(filtered_receipts)
        }
    })
    


@finance_bp.route('/upload', methods=['POST'])
@login_required
def upload_csv():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400
        
    try:
        # Read CSV directly from the request stream
        df = pd.read_csv(file)
        
        # Standardize column names (case-insensitive)
        df.columns = [c.strip().capitalize() for c in df.columns]
        
        required_cols = ['Date', 'Type', 'Category', 'Amount']
        if not all(col in df.columns for col in required_cols):
            return jsonify({'error': f'CSV must contain columns: {", ".join(required_cols)}'}), 400

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
        df = df.dropna(subset=['Date'])

        count = 0
        for _, row in df.iterrows():
            # Skip invalid rows
            if pd.isna(row['Amount']) or pd.isna(row['Type']): continue
            
            new_tx = Transaction(
                date=str(row['Date']),
                type=str(row['Type']).capitalize(),
                category=str(row['Category']),
                amount=float(row['Amount']),
                description=str(row.get('Description', ''))
            )
            db.session.add(new_tx)
            count += 1
            
        db.session.commit()
        return jsonify({'message': f'Successfully imported {count} transactions.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error: {str(e)}'}), 500

@finance_bp.route('/manual', methods=['POST'])
@login_required
def manual_entry():
    data = request.json
    try:
        new_tx = Transaction(
            date=data.get('date'),
            type=data.get('type'),
            category=data.get('category'),
            amount=float(data.get('amount')),
            description=data.get('description', '')
        )
        db.session.add(new_tx)
        db.session.commit()
        return jsonify({'message': 'Transaction added successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add these routes to finance_app.py


@finance_bp.route('/api/ledger', methods=['GET'])
@login_required
def get_ledger():
    selected_type = request.args.get('type', '').strip()
    period = request.args.get('period', 'all')
    today = datetime.now().date()

    transactions = Transaction.query.all()

    results = []

    # Regular transactions: manual entries and Google Sheets
    for tx in transactions:
        if not _date_matches_period(tx.date, period, today):
            continue

        if selected_type and tx.type != selected_type:
            continue

        is_synced = tx.description == 'Google Sheet Sync'

        results.append({
            'id': tx.id,
            'date': _format_ledger_date(tx.date),
            'type': tx.type,
            'category': tx.category or 'Uncategorized',
            'amount': float(tx.amount or 0),
            'description': tx.description or '',
            'source': 'Google Sheets' if is_synced else 'Manual Entry',
            'is_synced': is_synced,
            'is_receipt': False,
            'read_only': is_synced
        })

    # Driver reimbursements are expenses and cannot be edited here.
    if not selected_type or selected_type == 'Expense':
        driver_receipts = Receipt.query.filter(
            Receipt.status.in_(['Approved', 'Paid'])
        ).all()

        for receipt in driver_receipts:
            if not _date_matches_period(receipt.date, period, today):
                continue

            results.append({
                'id': None,
                'receipt_id': receipt.id,
                'date': _format_ledger_date(receipt.date),
                'type': 'Expense',
                'category': (f"Driver Reimbursements – "f"{(receipt.category or 'Uncategorized').strip().title()}"),
                'amount': float(receipt.amount or 0),
                'description': (
                    f"{receipt.category} claim submitted by "
                    f"{receipt.driver_name}"
                ),
                'source': 'Driver Receipt',
                'is_synced': False,
                'is_receipt': True,
                'read_only': True
            })

    # Newest entries first
    results.sort(
        key=lambda item: item['date'],
        reverse=True
    )

    return jsonify({'transactions': results})


@finance_bp.route('/api/ledger/<int:id>/edit', methods=['POST'])
@login_required
def edit_ledger(id):
    tx = Transaction.query.get_or_404(id)
    # Prevent editing synced data
    if tx.description == 'Google Sheet Sync':
        return jsonify({'error': 'Cannot edit items synced from Google Sheets. Please edit the sheet directly.'}), 400
    
    data = request.json
    try:
        tx.date = data.get('date', tx.date)
        tx.type = data.get('type', tx.type)
        tx.category = data.get('category', tx.category)
        tx.amount = float(data.get('amount', tx.amount))
        db.session.commit()
        return jsonify({'message': 'Transaction updated.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@finance_bp.route('/api/ledger/<int:id>/delete', methods=['DELETE'])
@login_required
def delete_ledger(id):
    tx = Transaction.query.get_or_404(id)
    # Prevent deleting synced data
    if tx.description == 'Google Sheet Sync':
        return jsonify({'error': 'Cannot delete items synced from Google Sheets. Please edit the sheet directly.'}), 400
        
    try:
        db.session.delete(tx)
        db.session.commit()
        return jsonify({'message': 'Transaction deleted.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

