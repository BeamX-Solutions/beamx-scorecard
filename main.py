from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from typing import Dict, Literal, Optional
import datetime
import os
import base64
import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from openai import OpenAI
from supabase import create_client, Client
import resend
import logging

# Configure logging for application monitoring
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Business Scorecard API", version="2.1.0")

# CORS configuration for frontend access
origins = [
    "https://beamxsolutions.com",  # Production frontend on Netlify
    "http://localhost:3000",       # Development frontend
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI client with error handling
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")

try:
    client = OpenAI(api_key=openai_api_key)
    logger.info("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    raise ValueError(f"Failed to initialize OpenAI client: {e}")

# Initialize Supabase client for data persistence
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY environment variables must be set")

try:
    supabase: Client = create_client(supabase_url, supabase_key)
    logger.info("Supabase client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {e}")
    raise ValueError(f"Failed to initialize Supabase client: {e}")

# Initialize Resend client
resend_api_key = os.getenv("RESEND_API_KEY")
from_email = os.getenv("FROM_EMAIL", "noreply@beamxsolutions.com")  # Use your verified domain

if not resend_api_key:
    logger.warning("Resend API key not configured. Email functionality will be disabled.")
else:
    resend.api_key = resend_api_key
    logger.info("Resend client initialized successfully")

# Pydantic model for input validation and API documentation
class ScorecardInput(BaseModel):
    revenue: Literal[
        "Under $10K",
        "$10K–$50K",
        "$50K–$250K",
        "$250K–$1M",
        "Over $1M"
    ] = Field(..., description="Annual revenue range")

    profit_margin_known: Literal["Yes", "No"] = Field(
        ..., description="Whether profit margins are tracked"
    )

    monthly_expenses: Literal[
        "Unknown",
        "≤$500",
        "$500–$1K",
        "$1K–$5K",
        "$5K–$20K",
        "$20K+"
    ] = Field(..., description="Monthly operating expenses")

    cac_tracked: Literal["Yes", "No"] = Field(
        ..., description="Whether Customer Acquisition Cost is tracked"
    )

    retention_rate: Literal[
        "<10%",
        "10–25%",
        "25–50%",
        "50–75%",
        "75%+"
    ] = Field(..., description="Customer retention rate")

    digital_campaigns: Literal[
        "No",
        "Sometimes",
        "Consistently"
    ] = Field(..., description="Frequency of digital marketing campaigns")

    analytics_tools: Literal[
        "No",
        "Basic tools (Excel, etc.)",
        "Advanced or custom dashboards"
    ] = Field(..., description="Analytics tools usage")

    crm_used: Literal["Yes", "No"] = Field(
        ..., description="Whether CRM system is used"
    )

    data_mgmt: Literal[
        "Scattered or manual",
        "Somewhat structured",
        "Centralized and automated"
    ] = Field(..., description="Data management approach")

    sops_doc: Literal[
        "No",
        "Somewhat",
        "Fully documented"
    ] = Field(..., description="Standard Operating Procedures documentation level")

    team_size: Literal[
        "1 (solo)",
        "2–4",
        "5–10",
        "11–50",
        "50+"
    ] = Field(..., description="Team size")

    pain_point: Literal[
        "Not growing",
        "Systems are chaotic",
        "Don't know what to optimize",
        "Need to reduce cost",
        "Need funding",
        "Need more clients/customers",
        "Growing fast, need structure"
    ] = Field(..., description="Primary business pain point")

    industry: str = Field(..., min_length=1, max_length=100, description="Industry sector")

# Pydantic model for email request
class EmailRequest(BaseModel):
    email: EmailStr = Field(..., description="Recipient email address")
    result: Dict = Field(..., description="Assessment results")
    formData: ScorecardInput = Field(..., description="Original form data")

# Function to generate PDF report
def generate_pdf_report(result: Dict, form_data: ScorecardInput) -> io.BytesIO:
    """Generate a PDF report of the business assessment results"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=1*inch)
    styles = getSampleStyleSheet()
    story = []

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        textColor=colors.HexColor('#1f2937'),
        alignment=1  # Center alignment
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceAfter=12,
        textColor=colors.HexColor('#374151')
    )

    # Title and header
    story.append(Paragraph("Business Assessment Report", title_style))
    story.append(Paragraph("BeamX Solutions", styles['Normal']))
    story.append(Paragraph(f"Generated on {datetime.datetime.now().strftime('%B %d, %Y')}", styles['Normal']))
    story.append(Spacer(1, 20))

    # Executive Summary
    story.append(Paragraph("Executive Summary", heading_style))
    story.append(Paragraph(f"<b>Industry:</b> {form_data.industry}", styles['Normal']))
    story.append(Paragraph(f"<b>Team Size:</b> {form_data.team_size}", styles['Normal']))
    story.append(Paragraph(f"<b>Annual Revenue:</b> {form_data.revenue}", styles['Normal']))
    story.append(Paragraph(f"<b>Primary Pain Point:</b> {form_data.pain_point}", styles['Normal']))
    story.append(Spacer(1, 20))

    # Overall Score
    story.append(Paragraph("Overall Assessment", heading_style))
    story.append(Paragraph(f"<b>Total Score:</b> {result['total_score']}/100", styles['Normal']))
    story.append(Paragraph(f"<b>Business Maturity Level:</b> {result['label']}", styles['Normal']))
    story.append(Spacer(1, 20))

    # Score Breakdown Table
    story.append(Paragraph("Detailed Score Breakdown", heading_style))

    breakdown_data = [
        ['Category', 'Your Score', 'Max Score', 'Percentage'],
        ['Financial Health', f"{result['breakdown']['financial']}", '25', f"{(result['breakdown']['financial']/25)*100:.0f}%"],
        ['Growth Readiness', f"{result['breakdown']['growth']}", '25', f"{(result['breakdown']['growth']/25)*100:.0f}%"],
        ['Digital Maturity', f"{result['breakdown']['digital']}", '25', f"{(result['breakdown']['digital']/25)*100:.0f}%"],
        ['Operational Efficiency', f"{result['breakdown']['operations']}", '25', f"{(result['breakdown']['operations']/25)*100:.0f}%"],
    ]

    breakdown_table = Table(breakdown_data, colWidths=[2.5*inch, 1*inch, 1*inch, 1*inch])
    breakdown_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#1f2937')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb'))
    ]))

    story.append(breakdown_table)
    story.append(Spacer(1, 30))

    # Advisory Section
    story.append(Paragraph("Strategic Advisory & Recommendations", heading_style))

    # Clean up the advisory text and split into paragraphs
    advisory_text = result.get('advisory', '')
    advisory_paragraphs = advisory_text.split('\n')

    for para in advisory_paragraphs:
        if para.strip():
            if para.startswith('**') and para.endswith('**'):
                # Bold headers
                clean_para = para.strip('*')
                story.append(Paragraph(f"<b>{clean_para}</b>", styles['Normal']))
            elif para.startswith('•'):
                # Bullet points
                story.append(Paragraph(para, styles['Normal']))
            else:
                # Regular paragraphs
                story.append(Paragraph(para, styles['Normal']))
            story.append(Spacer(1, 6))

    story.append(Spacer(1, 30))

    # Next Steps and Contact Information
    story.append(Paragraph("Ready to Take Action?", heading_style))
    story.append(Paragraph("Based on your assessment results, BeamX Solutions can help you implement the strategic recommendations outlined above.", styles['Normal']))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Contact Us:</b>", styles['Normal']))
    story.append(Paragraph("🌐 Website: https://beamxsolutions.com", styles['Normal']))
    story.append(Paragraph("📧 Email: info@beamxsolutions.com", styles['Normal']))
    story.append(Paragraph("📞 Schedule a consultation: https://calendly.com/beamxsolutions", styles['Normal']))

    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer

# Function to send email with PDF attachment using Resend
def send_email_with_resend(recipient_email: str, result: Dict, form_data: ScorecardInput) -> bool:
    """Send assessment results via email with PDF attachment using Resend"""
    if not resend_api_key:
        logger.error("Resend API key not configured")
        return False

    try:
        # Generate PDF
        pdf_buffer = generate_pdf_report(result, form_data)
        pdf_content = pdf_buffer.read()
        pdf_base64 = base64.b64encode(pdf_content).decode()

        # Create email content - optimized for email clients
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>BeamX Solutions - Business Assessment Results</title>
            <!--[if mso]>
            <style type="text/css">
                body, table, td {{font-family: Arial, sans-serif !important;}}
            </style>
            <![endif]-->
        </head>
        <body style="margin: 0; padding: 0; background-color: white; font-family: Arial, Helvetica, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #white;">
                <tr>
                    <td align="center" style="padding: 20px 0;">
                        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5;">

                            <!-- Header -->
                            <tr>
                                <td style="background-color: #02428e; padding: 40px 20px; text-align: center;">
                                    <img src="https://beamxsolutions.com/asset-1-2.png" alt="BeamX Solutions" width="112" height="50" style="display: block; margin: 0 auto 24px;" />
                                    <h1 style="color: #ffffff; font-size: 36px; font-weight: 600; margin: 0; line-height: 48px; font-family: Arial, Helvetica, sans-serif;">
                                        Your Business<br>Assessment Results
                                    </h1>
                                </td>
                            </tr>

                            <!-- Spacer -->
                            <tr><td style="height: 28px;"></td></tr>

                            <!-- Introduction -->
                            <tr>
                                <td style="padding: 0 30px;">
                                    <p style="color: #1d1d1b; font-size: 14px; line-height: 20px; margin: 0;">
                                        Hello!<br><br>
                                        Thank you for completing the BeamX Solutions Business Assessment. Your tailored results are ready!
                                    </p>
                                </td>
                            </tr>

                            <!-- Spacer -->
                            <tr><td style="height: 28px;"></td></tr>

                            <!-- Score Card -->
                            <tr>
                                <td align="center">
                                    <table width="347" cellpadding="28" cellspacing="0" style="background-color: #008bd8; border-radius: 8px;">
                                        <tr>
                                            <td>
                                                <p style="color: #ffffff; font-size: 20px; font-weight: 700; line-height: 28px; margin: 0;">
                                                    Your Overall Score: {result['total_score']}/100
                                                </p>
                                                <p style="color: #ffffff; font-size: 12px; margin: 8px 0 0 0; line-height: 20px;">
                                                    <span style="font-weight: 700;">Business Maturity Level:</span>
                                                    <span style="font-weight: 500;"> {result['label']}</span>
                                                </p>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>

                            <!-- Spacer -->
                            <tr><td style="height: 28px;"></td></tr>

                            <!-- Score Breakdown Card -->
                            <tr>
                                <td style="padding: 0 30px;">
                                    <table width="100%" cellpadding="20" cellspacing="0" style="background-color: #ffffff; border-radius: 8px;">
                                        <tr>
                                            <td>
                                                <h2 style="color: #008bd8; font-size: 16px; font-weight: 700; margin: 0 0 24px 0;">Score Breakdown</h2>

                                                <!-- Financial Health -->
                                                <p style="color: #1d1d1b; font-size: 14px; line-height: 20px; margin: 0 0 12px 0;">
                                                    <span style="font-weight: 600;">💰 Financial Health:</span> {result['breakdown']['financial']}/25
                                                </p>

                                                <!-- Growth Readiness -->
                                                <p style="color: #1d1d1b; font-size: 14px; line-height: 20px; margin: 0 0 12px 0;">
                                                    <span style="font-weight: 600;">📈 Growth Readiness:</span> {result['breakdown']['growth']}/25
                                                </p>

                                                <!-- Digital Maturity -->
                                                <p style="color: #1d1d1b; font-size: 14px; line-height="20px; margin: 0 0 12px 0;">
                                                    <span style="font-weight: 600;">💻 Digital Maturity:</span> {result['breakdown']['digital']}/25
                                                </p>

                                                <!-- Operational Efficiency -->
                                                <p style="color: #1d1d1b; font-size: 14px; line-height="20px; margin: 0;">
                                                    <span style="font-weight: 600;">⚙️ Operational Efficiency:</span> {result['breakdown']['operations']}/25
                                                </p>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>

                            <!-- Spacer -->
                            <tr><td style="height: 28px;"></td></tr>

                            <!-- PDF Info -->
                            <tr>
                                <td style="padding: 0 30px;">
                                    <p style="color: #1d1d1b; font-size: 14px; line-height: 20px; margin: 0;">
                                        Your detailed assessment report is attached as a PDF with personalized recommendations and next steps.
                                    </p>
                                </td>
                            </tr>

                            <!-- Spacer -->
                            <tr><td style="height: 28px;"></td></tr>

                            <!-- What's Next Title -->
                            <tr>
                                <td style="padding: 0 30px;">
                                    <h2 style="color: #008bd8; font-size: 16px; font-weight: 700; margin: 0;">What's Next?</h2>
                                </td>
                            </tr>

                            <!-- Spacer -->
                            <tr><td style="height: 28px;"></td></tr>

                            <!-- What's Next Content -->
                            <tr>
                                <td style="padding: 0 30px;">
                                    <p style="color: #1d1d1b; font-size: 14px; line-height: 20px; margin: 0;">
                                        Ready to transform these insights into growth? Our team specializes in helping {form_data.industry.lower()} businesses like yours overcome challenges like "{form_data.pain_point.lower()}" and achieve sustainable growth.
                                    </p>
                                </td>
                            </tr>

                            <!-- Spacer -->
                            <tr><td style="height: 28px;"></td></tr>

                            <!-- CTA Button -->
                            <tr>
                                <td align="center">
                                    <table cellpadding="0" cellspacing="0">
                                        <tr>
                                            <td style="background-color: #f27900; border-radius: 8px;">
                                                <a href="https://calendly.com/beamxsolutions" style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-size: 14px; font-weight: 600; font-family: Arial, Helvetica, sans-serif;">
                                                    Schedule Your Free Consultation
                                                </a>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>

                            <!-- Spacer -->
                            <tr><td style="height: 28px;"></td></tr>

                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #02428e; padding: 24px 20px; text-align: center;">
                                    <p style="color: #ffffff; font-size: 14px; margin: 0 0 16px 0;">Follow us on</p>

                                    <!-- Social Icons -->
                                    <table cellpadding="0" cellspacing="0" align="center" style="margin: 0 0 32px 0;">
                                        <tr>
                                            <!-- Facebook -->
                                            <td style="padding: 0 12px;">
                                                <a href="https://facebook.com/beamxsolutions" style="display: inline-block; text-decoration: none;">
                                                    <svg role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><title>Facebook</title><path d="M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z"/></svg>
                                                </a>
                                            </td>
                                            <!-- Instagram -->
                                            <td style="padding: 0 12px;">
                                                <a href="https://instagram.com/beamxsolutions" style="display: inline-block; text-decoration: none;">
                                                    <svg role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><title>Instagram</title><path d="M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077"/></svg>
                                                </a>
                                            </td>
                                            <!-- Twitter/X -->
                                            <td style="padding: 0 12px;">
                                                <a href="https://twitter.com/beamxsolutions" style="display: inline-block; text-decoration: none;">
                                                    <svg role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><title>X</title><path d="M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z"/></svg>
                                                </a>
                                            </td>
                                            <!-- LinkedIn -->
                                            <td style="padding: 0 12px;">
                                                <a href="https://linkedin.com/company/beamxsolutions" style="display: inline-block; text-decoration: none;">
                                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="display: block;">
                                                        <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" fill="#ffffff"/>
                                                    </svg>
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                    <p style="color: #ffffff; font-size: 14px; margin: 0 0 32px 0;">
                                        <a href="https://beamxsolutions.com" style="color: #ffffff; text-decoration: none;">www.beamxsolutions.com</a>
                                    </p>

                                    <p style="color: #ffffff; font-size: 14px; line-height: 20px; margin: 0 0 32px 0;">
                                        This email was generated from your business assessment <br>at
                                        <a href="https://beamxsolutions.com/tools/business-assessment" style="color: #ffffff; text-decoration: underline;">beamxsolutions.com/tools/business-assessment</a>
                                    </p>

                                    <p style="color: #008bd8; font-size: 14px; margin: 0;">
                                        Copyright © 2025 BeamXSolutions
                                    </p>
                                </td>
                            </tr>

                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        # Plain text version
        text_content = f"""
        Your Business Assessment Results - BeamX Solutions

        Hello!

        Thank you for completing the BeamX Solutions Business Assessment. Your results are ready!

        Your Score: {result['total_score']}/100 ({result['label']})

        Score Breakdown:
        • Financial Health: {result['breakdown']['financial']}/25
        • Growth Readiness: {result['breakdown']['growth']}/25
        • Digital Maturity: {result['breakdown']['digital']}/25
        • Operational Efficiency: {result['breakdown']['operations']}/25

        Your detailed assessment report is attached as a PDF with personalized recommendations.

        What's Next?
        Ready to transform these insights into growth? Our team specializes in helping {form_data.industry.lower()} businesses overcome challenges and achieve sustainable growth.

        Schedule Your Free Consultation: https://calendly.com/beamxsolutions

        Contact Us:
        Website: https://beamxsolutions.com
        Email: info@beamxsolutions.com

        Follow Us:
        Facebook: https://facebook.com/beamxsolutions
        Instagram: https://instagram.com/beamxsolutions
        Twitter/X: https://twitter.com/beamxsolutions
        LinkedIn: https://linkedin.com/company/beamxsolutions

        Best regards,
        The BeamX Solutions Team

        ---
        This email was generated from your business assessment at https://beamxsolutions.com/tools/business-assessment

        Copyright © 2025 BeamXSolutions
        """

        # Send email using Resend
        params = {
            "from": f"BeamX Solutions <{from_email}>",
            "to": [recipient_email],
            "subject": f"Your Business Assessment Results: {result['total_score']}/100 ({result['label']}) 📊",
            "html": html_content,
            "text": text_content,
            "attachments": [
                {
                    "filename": "BeamX_Business_Assessment_Report.pdf",
                    "content": pdf_base64
                }
            ]
        }

        email_response = resend.Emails.send(params)

        logger.info(f"Email sent successfully via Resend to {recipient_email}, ID: {email_response.get('id', 'unknown')}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email via Resend to {recipient_email}: {str(e)}")
        return False

# Scoring functions (unchanged from original)
def score_financial_health(data: ScorecardInput) -> int:
    """Calculate financial health score (0-25 points)"""
    revenue_map = {
        "Under $10K": 1,
        "$10K–$50K": 2,
        "$50K–$250K": 3,
        "$250K–$1M": 4,
        "Over $1M": 5
    }
    expenses_map = {
        "Unknown": 1,
        "≤$500": 2,
        "$500–$1K": 3,
        "$1K–$5K": 4,
        "$5K–$20K": 5,
        "$20K+": 6
    }

    revenue_score = revenue_map[data.revenue]
    profit_score = 1 if data.profit_margin_known == "Yes" else 0
    expenses_score = expenses_map[data.monthly_expenses]

    total_score = revenue_score + profit_score + expenses_score
    max_score = 5 + 1 + 6

    normalized_score = round((total_score / max_score) * 25)
    logger.info(f"Financial score: {normalized_score}/25 (raw: {total_score}/{max_score})")
    return normalized_score

def score_growth_readiness(data: ScorecardInput) -> int:
    """Calculate growth readiness score (0-25 points)"""
    retention_map = {
        "<10%": 1,
        "10–25%": 2,
        "25–50%": 3,
        "50–75%": 4,
        "75%+": 5
    }
    campaign_map = {
        "No": 1,
        "Sometimes": 3,
        "Consistently": 5
    }

    cac_score = 1 if data.cac_tracked == "Yes" else 0
    retention_score = retention_map[data.retention_rate]
    campaign_score = campaign_map[data.digital_campaigns]

    total_score = cac_score + retention_score + campaign_score
    max_score = 1 + 5 + 5

    normalized_score = round((total_score / max_score) * 25)
    logger.info(f"Growth score: {normalized_score}/25 (raw: {total_score}/{max_score})")
    return normalized_score

def score_digital_maturity(data: ScorecardInput) -> int:
    """Calculate digital maturity score (0-25 points)"""
    analytics_map = {
        "No": 1,
        "Basic tools (Excel, etc.)": 3,
        "Advanced or custom dashboards": 5
    }
    data_map = {
        "Scattered or manual": 1,
        "Somewhat structured": 3,
        "Centralized and automated": 5
    }

    analytics_score = analytics_map[data.analytics_tools]
    crm_score = 1 if data.crm_used == "Yes" else 0
    data_score = data_map[data.data_mgmt]

    total_score = analytics_score + crm_score + data_score
    max_score = 5 + 1 + 5

    normalized_score = round((total_score / max_score) * 25)
    logger.info(f"Digital score: {normalized_score}/25 (raw: {total_score}/{max_score})")
    return normalized_score

def score_operational_efficiency(data: ScorecardInput) -> int:
    """Calculate operational efficiency score (0-25 points)"""
    sop_map = {
        "No": 1,
        "Somewhat": 3,
        "Fully documented": 5
    }
    team_map = {
        "1 (solo)": 1,
        "2–4": 2,
        "5–10": 3,
        "11–50": 4,
        "50+": 5
    }
    pain_map = {
        "Not growing": 1,
        "Systems are chaotic": 2,
        "Don't know what to optimize": 3,
        "Need to reduce cost": 3,
        "Need funding": 4,
        "Need more clients/customers": 4,
        "Growing fast, need structure": 5
    }

    sop_score = sop_map[data.sops_doc]
    team_score = team_map[data.team_size]
    pain_score = pain_map[data.pain_point]

    total_score = sop_score + team_score + pain_score
    max_score = 5 + 5 + 5

    normalized_score = round((total_score / max_score) * 25)
    logger.info(f"Operations score: {normalized_score}/25 (raw: {total_score}/{max_score})")
    return normalized_score

# GPT-5 advisory generation function (unchanged from original)
async def generate_gpt5_advisory(input_data: ScorecardInput, scores: Dict[str, int]) -> str:
    """Generate advisory using GPT-5 with proper parameters"""

    prompt = f"""
    Write a comprehensive growth advisory for a {input_data.industry} business with these scores:
    • Financial Health: {scores['financial']}/25
    • Growth Readiness: {scores['growth']}/25
    • Digital Maturity: {scores['digital']}/25
    • Operations Efficiency: {scores['operations']}/25

    Business Context:
    • Revenue: {input_data.revenue}
    • Team Size: {input_data.team_size}
    • Primary Pain Point: {input_data.pain_point}

    Provide your response in this exact format with proper line breaks:

    **Strategic Insights:**

    • [Insight based on strongest and weakest areas]

    • [Industry-specific insight]

    • [Growth opportunity insight]

    **Action Steps:**

    • [Immediate actionable step addressing lowest score]

    • [Strategic step for next 90 days]

    CRITICAL FORMATTING RULES:
    - Each bullet point must be on its own line with a blank line after it
    - NEVER use em dashes (—) anywhere in your response
    - NEVER use hyphens (-) for emphasis or connecting ideas
    - Instead of dashes, use words like "and", "while", "to", or rephrase sentences completely
    - Use commas, periods, and conjunctions instead of any type of dash
    """

    try:
        logger.info("Calling GPT-5 API for advisory generation")

        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert business growth advisor specializing in data-driven recommendations. Provide specific, actionable advice based on the scorecard metrics."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_completion_tokens=400,
            verbosity="medium",
            reasoning_effort="minimal"
        )

        advisory = response.choices[0].message.content.strip()
        logger.info("GPT-5 advisory generated successfully")
        return advisory

    except Exception as e:
        logger.error(f"Error calling GPT-5 API: {e}")

        # Fallback advisory generation when API fails
        strongest_area = max(scores, key=scores.get)
        weakest_area = min(scores, key=scores.get)

        fallback_advisory = f"""
        **Strategic Insights:**
        • Your {strongest_area} capabilities (score: {scores[strongest_area]}/25) provide a solid foundation for growth in the {input_data.industry} sector, but {weakest_area} (score: {scores[weakest_area]}/25) needs immediate attention.

        • The current pain point of "{input_data.pain_point}" directly correlates with your scoring patterns and represents your primary growth bottleneck.

        • With {input_data.team_size} team members and {input_data.revenue} revenue, you're positioned for targeted improvements that can yield significant returns.

        **Action Steps:**
        • Address your {weakest_area} gap by implementing systematic tracking and measurement tools to improve this core business function.

        • Leverage your strength in {strongest_area} to create a 90 day improvement plan that builds momentum while fixing foundational issues.
                """.strip()

        return fallback_advisory

# Main API endpoint for generating scorecard reports (unchanged)
@app.post("/generate-report")
async def generate_report(input_data: ScorecardInput):
    """Generate comprehensive business scorecard report"""

    logger.info(f"Generating report for {input_data.industry} business")

    try:
        # Calculate all scoring dimensions
        financial_score = score_financial_health(input_data)
        growth_score = score_growth_readiness(input_data)
        digital_score = score_digital_maturity(input_data)
        operations_score = score_operational_efficiency(input_data)

        total_score = financial_score + growth_score + digital_score + operations_score

        # Determine business maturity classification
        if total_score >= 90:
            label = "Built for Scale"
        elif total_score >= 70:
            label = "Growth Ready"
        elif total_score >= 50:
            label = "Developing"
        else:
            label = "Early Stage"

        logger.info(f"Total score: {total_score}/100, Label: {label}")

        # Organize scores for response and advisory generation
        scores = {
            "financial": financial_score,
            "growth": growth_score,
            "digital": digital_score,
            "operations": operations_score
        }

        # Generate AI-powered business advisory
        advisory = await generate_gpt5_advisory(input_data, scores)

        # Create timestamp for record keeping
        timestamp = datetime.datetime.utcnow().isoformat()

        # Save assessment data to Supabase database
        try:
            logger.info("Saving assessment to Supabase")

            supabase_data = {
                "revenue": input_data.revenue,
                "profit_margin_known": input_data.profit_margin_known,
                "monthly_expenses": input_data.monthly_expenses,
                "cac_tracked": input_data.cac_tracked,
                "retention_rate": input_data.retention_rate,
                "digital_campaigns": input_data.digital_campaigns,
                "analytics_tools": input_data.analytics_tools,
                "crm_used": input_data.crm_used,
                "data_mgmt": input_data.data_mgmt,
                "sops_doc": input_data.sops_doc,
                "team_size": input_data.team_size,
                "pain_point": input_data.pain_point,
                "industry": input_data.industry,
                "scores": scores,
                "total_score": total_score,
                "advisory": advisory,
                "generated_at": timestamp
            }

            response = supabase.table("basic_assessments").insert(supabase_data).execute()
            logger.info(f"Successfully saved assessment with ID: {response.data[0]['id'] if response.data else 'unknown'}")

        except Exception as e:
            logger.error(f"Error saving to Supabase: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error saving assessment data: {str(e)}"
            )

        # Return comprehensive assessment results
        return {
            "total_score": total_score,
            "label": label,
            "breakdown": scores,
            "advisory": advisory,
            "industry": input_data.industry,
            "model_used": "gpt-5",
            "generated_at": timestamp,
            "assessment_summary": {
                "strongest_area": max(scores, key=scores.get),
                "weakest_area": min(scores, key=scores.get),
                "areas_for_improvement": [k for k, v in scores.items() if v < 15]
            }
        }

    except HTTPException:
        # Re-raise HTTPExceptions without modification
        raise
    except Exception as e:
        logger.error(f"Unexpected error in generate_report: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while generating the report: {str(e)}"
        )

# New endpoint for emailing results using Resend
@app.post("/email-results")
async def email_results(email_request: EmailRequest):
    """Send assessment results via email using Resend"""

    logger.info(f"Sending email via Resend to {email_request.email}")

    try:
        # Send email with PDF attachment using Resend
        success = send_email_with_resend(
            email_request.email,
            email_request.result,
            email_request.formData
        )

        if success:
            # Log the email send to Supabase
            try:
                supabase.table("email_logs").insert({
                    "recipient_email": email_request.email,
                    "total_score": email_request.result.get("total_score"),
                    "label": email_request.result.get("label"),
                    "industry": email_request.formData.industry,
                    "sent_at": datetime.datetime.utcnow().isoformat(),
                    "email_provider": "resend"
                }).execute()
                logger.info(f"Email send logged to database for {email_request.email}")
            except Exception as e:
                logger.warning(f"Failed to log email send to database: {e}")

            return {
                "status": "success",
                "message": "Email sent successfully via Resend",
                "provider": "resend"
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to send email via Resend"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in email_results: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while sending email: {str(e)}"
        )

# Health check endpoint for monitoring
@app.get("/health")
async def health_check():
    """Health check endpoint for system monitoring"""
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "model": "gpt-5",
        "version": "2.1.0",
        "email_provider": "resend" if resend_api_key else None,
        "email_configured": bool(resend_api_key)
    }

# Application entry point
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)