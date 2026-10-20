"""
Anaman Concierge Services — RFQ Quotation Web Form
Flask backend: form handling, PDF generation, SQLite storage
"""

import os
import json
import random
import string
from datetime import datetime, date  
from io import BytesIO
from dotenv import load_dotenv 

from flask import (
    Blueprint, render_template, request, jsonify, 
    send_file, flash, redirect, url_for, current_app # 
)
from flask_sqlalchemy import SQLAlchemy



from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether    
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

quotation_bp = Blueprint(
    'quotation', 
    __name__, 
    url_prefix='/quotation',
    template_folder='templates',
    static_folder='static'
)
db = SQLAlchemy()

def init_app(app):
    load_dotenv()  # Load environment variables from .env file
    app.config["SECRET_KEY"] = "acs-quotation-secret-key-change-in-prod"
    app.config["ORS_API_KEY"] = os.environ.get("ORS_API_KEY", "")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "instance", "quotations.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        os.makedirs(os.path.join(os.path.dirname(__file__), "instance"), exist_ok=True)
        db.create_all()



# ---------------------------------------------------------------------------
# Database Models
# ---------------------------------------------------------------------------

class Quotation(db.Model):
    __tablename__ = "quotations"

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(40), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Section 1 – Engagement Overview
    provider = db.Column(db.String(120), default="Anaman Concierge Services")
    vehicle = db.Column(db.String(60))
    event_start = db.Column(db.String(20))
    event_end = db.Column(db.String(20))
    location = db.Column(db.Text)
    total_runs = db.Column(db.String(20))
    requirements = db.Column(db.Text)

    # Section 4 – Terms
    quote_valid_until = db.Column(db.String(20))
    payment_terms = db.Column(db.Text)
    cancellation_policy = db.Column(db.Text)
    overtime_rate = db.Column(db.String(40))
    additional_charges = db.Column(db.Text)
    insurance_note = db.Column(
        db.String(200),
        default="Certificate of Insurance to be provided upon request",
    )

    # JSON blob for dynamic runs + pricing
    runs_json = db.Column(db.Text)  # list of run dicts
    total_quoted = db.Column(db.Float, default=0.0)

    def runs(self):
        if not self.runs_json:
            return []
        return json.loads(self.runs_json)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_invoice_number():
    """Unique invoice / quotation number for the whole document."""
    ts = datetime.now().strftime("%Y%m%d")
    rand = "".join(random.choices(string.digits, k=5))
    return f"ACS-{ts}-{rand}"


def generate_reservation_number():
    """Per-run reservation number (different from invoice number)."""
    return str(random.randint(100000, 999999))


def build_pdf(quotation: Quotation) -> BytesIO:
    """Generate a professional RFQ-style PDF matching the uploaded template style."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="MainTitle", fontSize=16, leading=20, textColor=colors.HexColor("#1a365d"),
        spaceAfter=4, fontName="Helvetica-Bold", alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        name="SubTitle", fontSize=10, leading=13, textColor=colors.HexColor("#4a5568"),
        spaceAfter=12, alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        name="SectionHead", fontSize=11, leading=14, textColor=colors.HexColor("#1a365d"),
        spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold",
        borderPadding=3
    ))
    styles.add(ParagraphStyle(
        name="BodyText2", fontSize=9, leading=12, textColor=colors.HexColor("#2d3748")
    ))
    styles.add(ParagraphStyle(
        name="Small", fontSize=8, leading=10, textColor=colors.HexColor("#4a5568")
    ))
    styles.add(ParagraphStyle(
        name="TableCell", fontSize=8, leading=10, textColor=colors.HexColor("#2d3748")
    ))
    styles.add(ParagraphStyle(
        name="TableHeader", fontSize=8, leading=10, fontName="Helvetica-Bold",
        textColor=colors.white
    ))
    styles.add(ParagraphStyle(
        name="Total", fontSize=11, leading=14, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a365d"), alignment=TA_RIGHT
    ))

    story = []
    runs = quotation.runs()

    # Header
    story.append(Paragraph("Anaman Concierge Services", styles["MainTitle"]))
    story.append(Paragraph(
        "Premium Charter &amp; Transportation Services<br/>REQUEST FOR QUOTATION",
        styles["SubTitle"]
    ))
    story.append(Paragraph(
        f"<b>Ref:</b> {quotation.invoice_number} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"<b>Issued:</b> {quotation.created_at.strftime('%B %d, %Y') if quotation.created_at else ''}",
        styles["Small"]
    ))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a365d")))
    story.append(Spacer(1, 8))

    # ----- Section 1: Engagement Overview -----
    story.append(Paragraph("1. ENGAGEMENT OVERVIEW", styles["SectionHead"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e0")))

    event_period = quotation.event_start or ""
    if quotation.event_end and quotation.event_end != quotation.event_start:
        event_period = f"{quotation.event_start} – {quotation.event_end}"

    overview_data = [
        [Paragraph("<b>Provider</b>", styles["TableCell"]),
         Paragraph(quotation.provider or "Anaman Concierge Services", styles["TableCell"])],
        [Paragraph("<b>Vehicle</b>", styles["TableCell"]),
         Paragraph(quotation.vehicle or "—", styles["TableCell"])],
        [Paragraph("<b>Event Period</b>", styles["TableCell"]),
         Paragraph(event_period or "—", styles["TableCell"])],
        [Paragraph("<b>Location</b>", styles["TableCell"]),
         Paragraph(quotation.location or "—", styles["TableCell"])],
        [Paragraph("<b>Total Runs</b>", styles["TableCell"]),
         Paragraph(str(quotation.total_runs or len(runs)), styles["TableCell"])],
        [Paragraph("<b>Requirements</b>", styles["TableCell"]),
         Paragraph(quotation.requirements or "—", styles["TableCell"])],
    ]
    t = Table(overview_data, colWidths=[1.6 * inch, 5.4 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf2f7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
    ]))
    story.append(t)

    # ----- Section 2: Service Schedule -----
    story.append(Paragraph("2. SERVICE SCHEDULE", styles["SectionHead"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e0")))
    story.append(Spacer(1, 4))

    if runs:
        header = [
            Paragraph("<b>Res. #</b>", styles["TableHeader"]),
            Paragraph("<b>Date</b>", styles["TableHeader"]),
            Paragraph("<b>Pick-Up</b>", styles["TableHeader"]),
            Paragraph("<b>Type</b>", styles["TableHeader"]),
            Paragraph("<b>Route</b>", styles["TableHeader"]),
            Paragraph("<b>Pax</b>", styles["TableHeader"]),
            Paragraph("<b>Loop / Flight Details</b>", styles["TableHeader"]),
        ]
        schedule_rows = [header]
        for r in runs:
            route_str = f"{r.get('pickup_location', '')} → {r.get('dropoff_location', '')}"
            schedule_rows.append([
                Paragraph(str(r.get("reservation_number", "")), styles["TableCell"]),
                Paragraph(str(r.get("date", "")), styles["TableCell"]),
                Paragraph(str(r.get("pickup_time", "")), styles["TableCell"]),
                Paragraph(str(r.get("type", "")), styles["TableCell"]),
                Paragraph(route_str, styles["TableCell"]),
                Paragraph(str(r.get("passengers", "")), styles["TableCell"]),
                Paragraph(str(r.get("loop_details", "") or "—"), styles["TableCell"]),
            ])
        col_w = [0.7*inch, 0.75*inch, 0.65*inch, 0.95*inch, 1.8*inch, 0.5*inch, 1.65*inch]
        st = Table(schedule_rows, colWidths=col_w, repeatRows=1)
        st.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f7fafc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f7fafc"), colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#1a365d")),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e0")),
        ]))
        story.append(st)
    else:
        story.append(Paragraph("No runs defined.", styles["BodyText2"]))

    # ----- Section 3: Pricing & Quotation -----
    story.append(Paragraph("3. PRICING &amp; QUOTATION", styles["SectionHead"]))
    story.append(Paragraph(
        "Best rate per run inclusive of driver, fuel, and standard tolls unless noted. All amounts in USD.",
        styles["Small"]
    ))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e0")))
    story.append(Spacer(1, 4))

    if runs:
        price_header = [
            Paragraph("<b>Res. #</b>", styles["TableHeader"]),
            Paragraph("<b>Date</b>", styles["TableHeader"]),
            Paragraph("<b>Type</b>", styles["TableHeader"]),
            Paragraph("<b>Route</b>", styles["TableHeader"]),
            Paragraph("<b>Quoted Rate (USD)</b>", styles["TableHeader"]),
        ]
        price_rows = [price_header]
        for r in runs:
            route_str = f"{r.get('pickup_location', '')} → {r.get('dropoff_location', '')}"
            rate = r.get("quoted_rate")
            rate_str = f"${float(rate):,.2f}" if rate not in (None, "", "None") else "—"
            price_rows.append([
                Paragraph(str(r.get("reservation_number", "")), styles["TableCell"]),
                Paragraph(str(r.get("date", "")), styles["TableCell"]),
                Paragraph(str(r.get("type", "")), styles["TableCell"]),
                Paragraph(route_str, styles["TableCell"]),
                Paragraph(rate_str, styles["TableCell"]),
            ])
        # Total row
        n = len(runs)
        total_str = f"${quotation.total_quoted:,.2f}" if quotation.total_quoted else "—"
        price_rows.append([
            Paragraph("", styles["TableCell"]),
            Paragraph("", styles["TableCell"]),
            Paragraph("", styles["TableCell"]),
            Paragraph(f"<b>TOTAL QUOTED AMOUNT ({n} run{'s' if n != 1 else ''})</b>", styles["TableCell"]),
            Paragraph(f"<b>{total_str}</b>", styles["TableCell"]),
        ])
        pt = Table(price_rows, colWidths=[0.85*inch, 0.9*inch, 1.1*inch, 2.8*inch, 1.35*inch])
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ebf8ff")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.HexColor("#f7fafc"), colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (4, 0), (4, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#1a365d")),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e0")),
        ]))
        story.append(pt)

    # ----- Section 4: Terms & Conditions -----
    story.append(Paragraph("4. TERMS &amp; CONDITIONS", styles["SectionHead"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e0")))

    terms_data = []
    if quotation.quote_valid_until:
        terms_data.append([
            Paragraph("<b>Quote Valid Until</b>", styles["TableCell"]),
            Paragraph(quotation.quote_valid_until, styles["TableCell"]),
        ])
    if quotation.payment_terms:
        terms_data.append([
            Paragraph("<b>Payment Terms</b>", styles["TableCell"]),
            Paragraph(quotation.payment_terms, styles["TableCell"]),
        ])
    if quotation.cancellation_policy:
        terms_data.append([
            Paragraph("<b>Cancellation Policy</b>", styles["TableCell"]),
            Paragraph(quotation.cancellation_policy, styles["TableCell"]),
        ])
    terms_data.append([
        Paragraph("<b>Overtime Rate</b>", styles["TableCell"]),
        Paragraph(
            f"${quotation.overtime_rate} per hour beyond scheduled drop-off"
            if quotation.overtime_rate else "—",
            styles["TableCell"]
        ),
    ])
    terms_data.append([
        Paragraph("<b>Additional Charges</b>", styles["TableCell"]),
        Paragraph(quotation.additional_charges or "Tolls / Parking / Fuel Surcharge as incurred", styles["TableCell"]),
    ])
    terms_data.append([
        Paragraph("<b>Insurance</b>", styles["TableCell"]),
        Paragraph(quotation.insurance_note or "Certificate of Insurance to be provided upon request", styles["TableCell"]),
    ])

    tt = Table(terms_data, colWidths=[1.7 * inch, 5.3 * inch])
    tt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf2f7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
    ]))
    story.append(tt)

    # Footer
    story.append(Spacer(1, 18))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a365d")))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Thank you for choosing Anaman Concierge Services — Premium Charter &amp; Transportation",
        styles["Small"]
    ))
    story.append(Paragraph(
        "Iowa City, IA &nbsp;|&nbsp; anamancs@gmail.com &nbsp;|&nbsp; 1-888-723-8112",
        styles["Small"]
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@quotation_bp.route("/")
def index():
    return render_template("form.html")


@quotation_bp.route("/api/reservation-number")
def api_reservation_number():
    return jsonify({"reservation_number": generate_reservation_number()})


@quotation_bp.route("/api/geocode/autocomplete")
def api_geocode_autocomplete():
    """Proxy OpenRouteService autocomplete so the API key stays on the server."""
    import urllib.request
    import urllib.parse
    text = (request.args.get("text") or "").strip()
    if len(text) < 2:
        return jsonify({"features": []})
    api_key = current_app.config.get("ORS_API_KEY") or ""
    if not api_key:
        return jsonify({"features": [], "error": "ORS_API_KEY not configured"}), 503
    params = {
        "api_key": api_key,
        "text": text,
        "boundary.country": "US",
        "size": 6,
        # Bias toward Iowa / Eastern Iowa
        "focus.point.lon": "-91.53",
        "focus.point.lat": "41.66",
    }
    url = "https://api.openrouteservice.org/geocode/autocomplete?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ACS-Quotation-App/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        # Normalize to a simple list of {label, lon, lat}
        features = []
        for f in data.get("features") or []:
            props = f.get("properties") or {}
            coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
            label = props.get("label") or props.get("name") or ""
            if label:
                features.append({
                    "label": label,
                    "lon": coords[0],
                    "lat": coords[1],
                })
        return jsonify({"features": features})
    except Exception as e:
        return jsonify({"features": [], "error": str(e)}), 502


@quotation_bp.route("/submit", methods=["POST"])
def submit():
    """Receive form data, save to DB, generate PDF, return download."""
    try:
        # Section 1
        vehicle = request.form.get("vehicle", "").strip()
        event_start = request.form.get("event_start", "").strip()
        event_end = request.form.get("event_end", "").strip()
        location = request.form.get("location", "").strip()
        total_runs = request.form.get("total_runs", "").strip()
        requirements = request.form.get("requirements", "").strip()

        # Section 4
        quote_valid_until = request.form.get("quote_valid_until", "").strip()
        payment_terms = request.form.get("payment_terms", "").strip()
        cancellation_policy = request.form.get("cancellation_policy", "").strip()
        overtime_rate = request.form.get("overtime_rate", "").strip()
        additional_charges = request.form.get("additional_charges", "").strip()

        # Dynamic runs (sent as JSON string from frontend)
        runs_raw = request.form.get("runs_json", "[]")
        try:
            runs = json.loads(runs_raw)
        except json.JSONDecodeError:
            runs = []

        # Calculate total
        total = 0.0
        for r in runs:
            try:
                rate = float(r.get("quoted_rate") or 0)
                r["quoted_rate"] = rate
                total += rate
            except (TypeError, ValueError):
                r["quoted_rate"] = None

        invoice_number = generate_invoice_number()

        quotation = Quotation(
            invoice_number=invoice_number,
            provider="Anaman Concierge Services",
            vehicle=vehicle,
            event_start=event_start,
            event_end=event_end or event_start,
            location=location,
            total_runs=total_runs or str(len(runs)),
            requirements=requirements,
            quote_valid_until=quote_valid_until or None,
            payment_terms=payment_terms or None,
            cancellation_policy=cancellation_policy or None,
            overtime_rate=overtime_rate or None,
            additional_charges=additional_charges or None,
            runs_json=json.dumps(runs),
            total_quoted=total,
        )
        db.session.add(quotation)
        db.session.commit()

        # Generate PDF
        pdf_buffer = build_pdf(quotation)
        filename = f"ACS_Quotation_{invoice_number}.pdf"

        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Error generating quotation: {str(e)}", "error")
        return redirect(url_for("quotation.index"))


@quotation_bp.route("/quotations")
def list_quotations():
    """Simple list of stored quotations (admin view)."""
    items = Quotation.query.order_by(Quotation.created_at.desc()).limit(50).all()
    return render_template("list.html", quotations=items)


@quotation_bp.route("/quotations/<int:qid>/pdf")
def download_pdf(qid):
    q = Quotation.query.get_or_404(qid)
    pdf_buffer = build_pdf(q)
    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"ACS_Quotation_{q.invoice_number}.pdf",
    )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

