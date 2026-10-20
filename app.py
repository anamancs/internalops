from flask import Flask, render_template
from fleet_app import fleet_bp
# ✅ Importing the REAL quotation app from its folder
from acs_quotation_app.quotation_app import quotation_bp, init_app as init_quotation_app
from hotel_app import hotel_bp 

app = Flask(__name__)

# Initialize the quotation app's database
init_quotation_app(app)

# Register blueprints
app.register_blueprint(fleet_bp)
app.register_blueprint(quotation_bp)

@app.route('/')
def landing_page():
    return render_template('landing.html')

if __name__ == '__main__':
    app.run(debug=True)