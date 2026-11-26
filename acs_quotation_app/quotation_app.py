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

from extensions import db

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    LongTable,
    TableStyle,
    HRFlowable,
    KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from xml.sax.saxutils import escape #starts here
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
#db = SQLAlchemy()

def init_app(app):
    load_dotenv()  # Load environment variables from .env file
    app.config["SECRET_KEY"] = "acs-quotation-secret-key-change-in-prod"
    app.config["ORS_API_KEY"] = os.environ.get("ORS_API_KEY", "")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "instance", "quotations.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    #db.init_app(app)




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
    """
    Generate an executive-style ACS quotation PDF.

    Preserves the existing Quotation model and all stored fields.
    Uses adaptive pagination for service schedules and pricing tables.
    """

    buffer = BytesIO()

    # ---------------------------------------------------------
    # ACS BRAND PALETTE
    # ---------------------------------------------------------

    NAVY = colors.HexColor("#142641")
    NAVY_LIGHT = colors.HexColor("#203B60")
    BLUE = colors.HexColor("#3B78B8")
    GOLD = colors.HexColor("#C6A15B")
    TEXT = colors.HexColor("#29384C")
    MUTED = colors.HexColor("#718096")
    BORDER = colors.HexColor("#E2E8F0")
    LIGHT = colors.HexColor("#F4F7FB")
    PALE_BLUE = colors.HexColor("#EDF3F9")
    WHITE = colors.white

    # ---------------------------------------------------------
    # DOCUMENT SETUP
    # ---------------------------------------------------------

    page_width, page_height = letter

    left_margin = 0.55 * inch
    right_margin = 0.55 * inch
    top_margin = 0.88 * inch
    bottom_margin = 0.68 * inch

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=right_margin,
        leftMargin=left_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        title=f"ACS Quotation - {quotation.invoice_number}",
        author="Anaman Concierge Services",
        subject="Transportation Service Quotation",
    )

    usable_width = page_width - left_margin - right_margin

    # ---------------------------------------------------------
    # SAFE TEXT HELPERS
    # ---------------------------------------------------------

    def safe_text(value, fallback="—"):
        """
        Escape user-entered text before passing it to ReportLab.
        Preserve line breaks without allowing arbitrary markup.
        """
        if value is None:
            return fallback

        value = str(value).strip()

        if not value:
            return fallback

        return escape(value).replace("\n", "<br/>")

    def para(value, style, fallback="—"):
        return Paragraph(safe_text(value, fallback), style)

    def money(value):
        try:
            return f"${float(value or 0):,.2f}"
        except (TypeError, ValueError):
            return "$0.00"

    def section_heading(number, title, description=None):
        heading = Paragraph(
            f'<font color="#C6A15B">{number}</font>'
            f'&nbsp;&nbsp;{escape(title.upper())}',
            styles["SectionTitle"]
        )

        elements = [heading]

        if description:
            elements.append(
                Paragraph(
                    escape(description),
                    styles["SectionDescription"]
                )
            )

        elements.append(
            HRFlowable(
                width="100%",
                thickness=0.8,
                color=BORDER,
                spaceBefore=3,
                spaceAfter=9
            )
        )

        return KeepTogether(elements)

    # ---------------------------------------------------------
    # TYPOGRAPHY
    # ---------------------------------------------------------

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="HeroTitle",
        fontName="Helvetica-Bold",
        fontSize=19,
        leading=23,
        textColor=WHITE,
        spaceAfter=5,
    ))

    styles.add(ParagraphStyle(
        name="HeroSubtitle",
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#D8E2EF"),
    ))

    styles.add(ParagraphStyle(
        name="HeroLabel",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#D8E2EF"),
        alignment=TA_RIGHT,
    ))

    styles.add(ParagraphStyle(
        name="HeroAmount",
        fontName="Helvetica-Bold",
        fontSize=21,
        leading=25,
        textColor=WHITE,
        alignment=TA_RIGHT,
    ))

    styles.add(ParagraphStyle(
        name="Reference",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=NAVY,
    ))

    styles.add(ParagraphStyle(
        name="Meta",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=MUTED,
    ))

    styles.add(ParagraphStyle(
        name="SectionTitle",
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=NAVY,
        spaceBefore=11,
        spaceAfter=4,
    ))

    styles.add(ParagraphStyle(
        name="SectionDescription",
        fontName="Helvetica",
        fontSize=7.8,
        leading=11,
        textColor=MUTED,
        spaceAfter=3,
    ))

    styles.add(ParagraphStyle(
        name="Body",
        fontName="Helvetica",
        fontSize=8.3,
        leading=12,
        textColor=TEXT,
    ))

    styles.add(ParagraphStyle(
        name="BodySmall",
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=TEXT,
    ))

    styles.add(ParagraphStyle(
        name="Label",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=MUTED,
    ))

    styles.add(ParagraphStyle(
        name="Value",
        fontName="Helvetica",
        fontSize=8.2,
        leading=11,
        textColor=TEXT,
    ))

    styles.add(ParagraphStyle(
        name="TableHeaderModern",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=WHITE,
    ))

    styles.add(ParagraphStyle(
        name="TableBodyModern",
        fontName="Helvetica",
        fontSize=7,
        leading=9.5,
        textColor=TEXT,
    ))

    styles.add(ParagraphStyle(
        name="TableBodyBold",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9.5,
        textColor=NAVY,
    ))

    styles.add(ParagraphStyle(
        name="TotalLabel",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=NAVY,
        alignment=TA_RIGHT,
    ))

    styles.add(ParagraphStyle(
        name="TotalAmount",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=NAVY,
        alignment=TA_RIGHT,
    ))

    styles.add(ParagraphStyle(
        name="FooterNote",
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=MUTED,
        alignment=TA_CENTER,
    ))

    styles.add(ParagraphStyle(
        name="EmptyNote",
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=12,
        textColor=MUTED,
    ))

    # ---------------------------------------------------------
    # PAGE HEADER AND FOOTER
    # ---------------------------------------------------------

    def draw_page_chrome(canvas, document):
        canvas.saveState()

        # Top navy brand strip
        canvas.setFillColor(NAVY)
        canvas.rect(
            0,
            page_height - 0.48 * inch,
            page_width,
            0.48 * inch,
            stroke=0,
            fill=1
        )

        # Gold accent
        canvas.setFillColor(GOLD)
        canvas.rect(
            0,
            page_height - 0.48 * inch,
            0.07 * inch,
            0.48 * inch,
            stroke=0,
            fill=1
        )

        # Brand name
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(
            left_margin,
            page_height - 0.30 * inch,
            "ANAMAN CONCIERGE SERVICES"
        )

        # Header descriptor
        canvas.setFillColor(colors.HexColor("#D8E2EF"))
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(
            page_width - right_margin,
            page_height - 0.29 * inch,
            "EXECUTIVE TRANSPORTATION"
        )

        # Footer divider
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.7)
        canvas.line(
            left_margin,
            0.49 * inch,
            page_width - right_margin,
            0.49 * inch
        )

        # Footer company details
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)

        canvas.drawString(
            left_margin,
            0.32 * inch,
            "ANAMAN CONCIERGE SERVICES  |  anamancs@gmail.com  |  1-888-723-8112"
        )

        # Reference and page number
        canvas.drawRightString(
            page_width - right_margin,
            0.32 * inch,
            f"{quotation.invoice_number}  |  PAGE {document.page}"
        )

        canvas.restoreState()

    # ---------------------------------------------------------
    # QUOTATION DATA
    # ---------------------------------------------------------

    try:
        runs = quotation.runs() or []
    except (ValueError, TypeError, json.JSONDecodeError):
        runs = []

    created_date = (
        quotation.created_at.strftime("%B %d, %Y")
        if quotation.created_at
        else datetime.now().strftime("%B %d, %Y")
    )

    event_period = quotation.event_start or "Not specified"

    if quotation.event_end and quotation.event_end != quotation.event_start:
        event_period = f"{quotation.event_start} to {quotation.event_end}"

    run_count = len(runs)
    total_amount = float(quotation.total_quoted or 0)

    story = []

    # ---------------------------------------------------------
    # COMPACT PROPOSAL HEADER
    # ---------------------------------------------------------

    story.append(Spacer(1, 5))

    hero_left = [
        Paragraph(
            "TRANSPORTATION<br/>SERVICE QUOTATION",
            styles["HeroTitle"]
        ),
        Paragraph(
            "A tailored transportation proposal from Anaman Concierge Services.",
            styles["HeroSubtitle"]
        ),
    ]

    hero_right = [
        Paragraph("TOTAL QUOTED AMOUNT", styles["HeroLabel"]),
        Paragraph(money(total_amount), styles["HeroAmount"]),
        Paragraph(
            f"{run_count} scheduled run{'s' if run_count != 1 else ''}",
            styles["HeroLabel"]
        ),
    ]

    hero = Table(
        [[hero_left, hero_right]],
        colWidths=[4.55 * inch, usable_width - 4.55 * inch],
    )

    hero.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 15),
        ("RIGHTPADDING", (0, 0), (-1, -1), 15),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LINEBEFORE", (1, 0), (1, 0), 1, GOLD),
    ]))

    story.append(hero)
    story.append(Spacer(1, 10))

    reference_data = [[
        Paragraph(
            f"<b>QUOTATION REFERENCE</b><br/>{safe_text(quotation.invoice_number)}",
            styles["Reference"]
        ),
        Paragraph(
            f"<b>ISSUE DATE</b><br/>{safe_text(created_date)}",
            styles["Meta"]
        ),
        Paragraph(
            f"<b>EVENT PERIOD</b><br/>{safe_text(event_period)}",
            styles["Meta"]
        ),
    ]]

    reference_table = Table(
        reference_data,
        colWidths=[
            usable_width * 0.34,
            usable_width * 0.27,
            usable_width * 0.39,
        ]
    )

    reference_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBEFORE", (1, 0), (2, 0), 0.5, BORDER),
    ]))

    story.append(reference_table)

    # ---------------------------------------------------------
    # SECTION 1: ENGAGEMENT OVERVIEW
    # ---------------------------------------------------------

    story.append(section_heading(
        "01",
        "Engagement Overview",
        "Summary of the proposed transportation engagement."
    ))

    overview_items = [
        ("Service Provider", quotation.provider or "Anaman Concierge Services"),
        ("Vehicle Category", quotation.vehicle or "—"),
        ("Event Period", event_period),
        ("Service Location", quotation.location or "—"),
        ("Total Runs", quotation.total_runs or str(run_count)),
        ("Special Requirements", quotation.requirements or "—"),
    ]

    overview_rows = []

    for i in range(0, len(overview_items), 2):
        left_label, left_value = overview_items[i]
        right_label, right_value = overview_items[i + 1]

        overview_rows.append([
            Paragraph(escape(left_label.upper()), styles["Label"]),
            para(left_value, styles["Value"]),
            Paragraph(escape(right_label.upper()), styles["Label"]),
            para(right_value, styles["Value"]),
        ])

    overview_table = Table(
        overview_rows,
        colWidths=[
            1.05 * inch,
            2.60 * inch,
            1.05 * inch,
            usable_width - 4.70 * inch,
        ],
    )

    overview_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
        ("BACKGROUND", (2, 0), (2, -1), PALE_BLUE),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    story.append(overview_table)

    # ---------------------------------------------------------
    # SECTION 2: SERVICE SCHEDULE
    # ---------------------------------------------------------

    story.append(section_heading(
        "02",
        "Transportation Schedule",
        "Individual service arrangements and transportation details."
    ))

    if runs:
        schedule_header = [
            Paragraph("RES. #", styles["TableHeaderModern"]),
            Paragraph("DATE", styles["TableHeaderModern"]),
            Paragraph("PICK-UP", styles["TableHeaderModern"]),
            Paragraph("TYPE", styles["TableHeaderModern"]),
            Paragraph("TRANSPORTATION ROUTE", styles["TableHeaderModern"]),
            Paragraph("PAX", styles["TableHeaderModern"]),
            Paragraph("FLIGHT / LOOP DETAILS", styles["TableHeaderModern"]),
        ]

        schedule_rows = [schedule_header]

        for r in runs:
            pickup = r.get("pickup_location", "")
            dropoff = r.get("dropoff_location", "")

            route = f"{pickup} to {dropoff}" if pickup or dropoff else "—"

            schedule_rows.append([
                para(r.get("reservation_number"), styles["TableBodyModern"]),
                para(r.get("date"), styles["TableBodyModern"]),
                para(r.get("pickup_time"), styles["TableBodyModern"]),
                para(r.get("type"), styles["TableBodyModern"]),
                para(route, styles["TableBodyModern"]),
                para(r.get("passengers"), styles["TableBodyModern"]),
                para(r.get("loop_details"), styles["TableBodyModern"]),
            ])

        schedule_widths = [
            0.67 * inch,
            0.66 * inch,
            0.57 * inch,
            0.77 * inch,
            1.95 * inch,
            0.40 * inch,
            usable_width - (0.67 + 0.66 + 0.57 + 0.77 + 1.95 + 0.40) * inch,
        ]

        schedule_table = LongTable(
            schedule_rows,
            colWidths=schedule_widths,
            repeatRows=1,
            splitByRow=1,
            hAlign="LEFT",
        )

        schedule_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY_LIGHT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT, WHITE]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 1, GOLD),
            ("LINEBELOW", (0, 1), (-1, -1), 0.35, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))

        story.append(schedule_table)

    else:
        story.append(Paragraph(
            "No transportation runs were included in this quotation.",
            styles["EmptyNote"]
        ))

    # ---------------------------------------------------------
    # SECTION 3: PRICING & QUOTATION
    # ---------------------------------------------------------

    story.append(section_heading(
        "03",
        "Pricing & Quotation",
        "Quoted service rates and the total proposed engagement value. All amounts are in USD."
    ))

    if runs:
        price_header = [
            Paragraph("RESERVATION #", styles["TableHeaderModern"]),
            Paragraph("DATE", styles["TableHeaderModern"]),
            Paragraph("SERVICE TYPE", styles["TableHeaderModern"]),
            Paragraph("TRANSPORTATION ROUTE", styles["TableHeaderModern"]),
            Paragraph("QUOTED RATE (USD)", styles["TableHeaderModern"]),
        ]

        price_rows = [price_header]

        for r in runs:
            pickup = r.get("pickup_location", "")
            dropoff = r.get("dropoff_location", "")
            route = f"{pickup} to {dropoff}" if pickup or dropoff else "—"

            price_rows.append([
                para(r.get("reservation_number"), styles["TableBodyModern"]),
                para(r.get("date"), styles["TableBodyModern"]),
                para(r.get("type"), styles["TableBodyModern"]),
                para(route, styles["TableBodyModern"]),
                Paragraph(
                    money(r.get("quoted_rate")),
                    ParagraphStyle(
                        "PriceCell",
                        parent=styles["TableBodyModern"],
                        alignment=TA_RIGHT,
                    )
                ),
            ])

        price_rows.append([
            Paragraph("", styles["TableBodyModern"]),
            Paragraph("", styles["TableBodyModern"]),
            Paragraph("", styles["TableBodyModern"]),
            Paragraph(
                f"TOTAL QUOTED AMOUNT ({run_count} RUN{'S' if run_count != 1 else ''})",
                styles["TotalLabel"]
            ),
            Paragraph(money(total_amount), styles["TotalAmount"]),
        ])

        price_widths = [
            0.82 * inch,
            0.75 * inch,
            0.95 * inch,
            3.15 * inch,
            usable_width - (0.82 + 0.75 + 0.95 + 3.15) * inch,
        ]

        pricing_table = LongTable(
            price_rows,
            colWidths=price_widths,
            repeatRows=1,
            splitByRow=1,
            hAlign="LEFT",
        )

        pricing_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY_LIGHT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [LIGHT, WHITE]),
            ("BACKGROUND", (0, -1), (-1, -1), PALE_BLUE),
            ("LINEABOVE", (0, -1), (-1, -1), 1.2, GOLD),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
            ("LINEBELOW", (0, 1), (-1, -2), 0.35, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("SPAN", (0, -1), (2, -1)),
        ]))

        story.append(pricing_table)

    else:
        story.append(Paragraph(
            "No individual run pricing is available.",
            styles["EmptyNote"]
        ))

    # ---------------------------------------------------------
    # SECTION 4: TERMS & CONDITIONS
    # ---------------------------------------------------------

    story.append(section_heading(
        "04",
        "Terms & Conditions",
        "Commercial conditions and additional information governing this quotation."
    ))

    terms_items = []

    if quotation.quote_valid_until:
        terms_items.append((
            "Quotation Valid Until",
            quotation.quote_valid_until
        ))

    if quotation.payment_terms:
        terms_items.append((
            "Payment Terms",
            quotation.payment_terms
        ))

    if quotation.cancellation_policy:
        terms_items.append((
            "Cancellation Policy",
            quotation.cancellation_policy
        ))

    terms_items.append((
        "Overtime Rate",
    (
        f"${quotation.overtime_rate} per hour beyond scheduled drop-off"
        if quotation.overtime_rate
        else "Not specified"
    )
))

    terms_items.append((
        "Additional Charges",
        quotation.additional_charges or
        "Tolls / Parking / Fuel Surcharge as incurred"
    ))

    terms_items.append((
        "Insurance",
        quotation.insurance_note or
        "Certificate of Insurance to be provided upon request"
    ))

    terms_rows = []

    for label, value in terms_items:
        terms_rows.append([
            Paragraph(escape(label.upper()), styles["Label"]),
            para(value, styles["Value"]),
        ])

    terms_table = Table(
        terms_rows,
        colWidths=[1.65 * inch, usable_width - 1.65 * inch],
        hAlign="LEFT",
    )

    terms_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
        ("BACKGROUND", (1, 0), (1, -1), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.45, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))

    story.append(terms_table)

    # ---------------------------------------------------------
    # CLOSING MESSAGE
    # ---------------------------------------------------------

    story.append(Spacer(1, 15))

    closing = Table(
        [[
            Paragraph(
                "<b>THANK YOU FOR CONSIDERING ACS</b><br/>"
                "We appreciate the opportunity to provide your transportation services.",
                styles["Body"]
            )
        ]],
        colWidths=[usable_width],
    )

    closing.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEBEFORE", (0, 0), (0, 0), 3, GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))

    story.append(closing)

    story.append(Spacer(1, 8))

    story.append(Paragraph(
        "Anaman Concierge Services | Iowa City, Iowa | anamancs.com",
        styles["FooterNote"]
    ))

    # ---------------------------------------------------------
    # BUILD PDF WITH AUTOMATIC PAGINATION
    # ---------------------------------------------------------

    doc.build(
        story,
        onFirstPage=draw_page_chrome,
        onLaterPages=draw_page_chrome,
    )

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
    url = "https://api.heigit.org/pelias/v1/autocomplete?" + urllib.parse.urlencode(params)
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

