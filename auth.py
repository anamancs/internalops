import os
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db  # ✅ Import the shared db
from datetime import datetime

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
login_manager = LoginManager()

# --- User Model ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='admin')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Initialization ---
def init_auth(app):
    # ✅ Set the DB path to auth.db so it doesn't mix with quotations.db
    base_dir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(base_dir, 'auth.db')}"
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'acs-internal-portal-secret-key')
    
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'You must be logged in as an Admin to view this page.'
    login_manager.login_message_category = 'warning'

# --- Routes ---
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/')
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or '/')
        else:
            flash('Invalid username or password', 'danger')
    return render_template('login.html')



@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/')