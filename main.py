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
        
        # Create email content
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>BeamX Solutions - Business Assessment Results</title>
            <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&family=Roboto:wght@400;600;700&display=swap" rel="stylesheet">
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}

                body {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    background-color: #f5f5f5;
                    display: flex;
                    justify-content: center;
                    min-height: 100vh;
                }}

                .container {{
                    width: 600px;
                    background-color: #f5f5f5;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 28px;
                }}

                .header {{
                    width: 100%;
                    background-color: #02428e;
                    padding: 40px 0;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 24px;
                }}

                .logo {{
                    width: 112px;
                    height: 50px;
                }}

                .header h1 {{
                    font-family: 'Poppins', Helvetica, sans-serif;
                    font-weight: 600;
                    color: white;
                    font-size: 36px;
                    text-align: center;
                    line-height: 48px;
                    margin: 0;
                }}

                .section {{
                    width: 540px;
                }}

                .section p {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-weight: 400;
                    color: #1d1d1b;
                    font-size: 14px;
                    line-height: 20px;
                }}

                .score-card {{
                    width: 347px;
                    background-color: #008bd8;
                    border-radius: 8px;
                    padding: 28px;
                    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
                }}

                .score-card-content {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-size: 24px;
                    line-height: 24px;
                }}

                .score-card-content .score {{
                    font-weight: 700;
                    color: white;
                    font-size: 24px;
                    line-height: 32px;
                }}

                .score-card-content .level-label {{
                    font-weight: 700;
                    color: white;
                    font-size: 16px;
                    line-height: 32px;
                }}

                .score-card-content .level-value {{
                    font-weight: 500;
                    color: white;
                    font-size: 16px;
                    line-height: 32px;
                }}

                .breakdown-card {{
                    width: 540px;
                    background-color: white;
                    border-radius: 8px;
                    padding: 20px;
                    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
                }}

                .breakdown-card h2 {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-weight: 700;
                    color: #008bd8;
                    font-size: 16px;
                    line-height: 20px;
                    margin-bottom: 24px;
                }}

                .breakdown-items {{
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }}

                .breakdown-item {{
                    display: flex;
                    align-items: center;
                    gap: 7px;
                }}

                .breakdown-item img {{
                    width: 16px;
                    height: 16px;
                }}

                .breakdown-item-text {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-size: 14px;
                    line-height: 20px;
                    color: #1d1d1b;
                    white-space: nowrap;
                }}

                .breakdown-item-text .label {{
                    font-weight: 600;
                }}

                .breakdown-item-text .score {{
                    font-weight: 400;
                }}

                .section-title {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-weight: 700;
                    color: #008bd8;
                    font-size: 16px;
                    line-height: 20px;
                }}

                .cta-button {{
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    padding: 10px;
                    background-color: #f27900;
                    border-radius: 8px;
                    border: none;
                    cursor: pointer;
                    transition: background-color 0.3s;
                    text-decoration: none;
                }}

                .cta-button:hover {{
                    background-color: #d96d00;
                }}

                .cta-button span {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-weight: 600;
                    color: white;
                    font-size: 14px;
                    text-align: center;
                    line-height: 20px;
                    white-space: nowrap;
                }}

                .footer {{
                    width: 100%;
                    background-color: #02428e;
                    padding: 24px 0;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 32px;
                }}

                .social-section {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 16px;
                }}

                .social-section p {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-weight: 400;
                    color: white;
                    font-size: 14px;
                    text-align: center;
                    letter-spacing: 0.1px;
                    line-height: 20px;
                }}

                .social-icons {{
                    display: flex;
                    align-items: center;
                    gap: 32px;
                    height: 24px;
                }}

                .social-icons img {{
                    width: 24px;
                    height: 24px;
                    cursor: pointer;
                }}

                .footer-text {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-weight: 400;
                    color: white;
                    font-size: 14px;
                    text-align: center;
                    letter-spacing: 0.1px;
                    line-height: 20px;
                }}

                .footer-link {{
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-weight: 600;
                    color: white;
                    text-decoration: underline;
                }}

                .footer-description {{
                    width: 538px;
                    font-family: 'Roboto', Helvetica, sans-serif;
                    font-weight: 400;
                    color: white;
                    font-size: 14px;
                    text-align: center;
                    line-height: 20px;
                }}

                .copyright {{
                    width: 600px;
                    font-family: 'Poppins', Helvetica, sans-serif;
                    font-weight: 400;
                    color: #008bd8;
                    font-size: 14px;
                    text-align: center;
                    letter-spacing: 0.1px;
                    line-height: 22px;
                }}

                a {{
                    color: inherit;
                    text-decoration: inherit;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <!-- Header -->
                <header class="header">
                    <!-- Replace the src with your local logo path -->
                    <img class="logo" alt="BeamX Solutions Logo" src="YOUR_LOGO_PATH_HERE.svg">
                    <h1>Your Business<br>Assessment Results</h1>
                </header>

                <!-- Introduction -->
                <section class="section">
                    <p>
                        Hello!<br><br>
                        Thank you for completing the BeamX Solutions Business Assessment. Your tailored results are ready!
                    </p>
                </section>

                <!-- Score Card -->
                <div class="score-card">
                    <div class="score-card-content">
                        <span class="score">Your Overall Score: {result['total_score']}/100<br></span>
                        <span class="level-label">Business Maturity Level:</span>
                        <span class="level-value"> {result['label']}</span>
                    </div>
                </div>

                <!-- Score Breakdown -->
                <div class="breakdown-card">
                    <h2>Score Breakdown</h2>
                    <div class="breakdown-items">
                        <div class="breakdown-item">
                            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M6 5.33333H10C10.1768 5.33333 10.3464 5.26309 10.4714 5.13807C10.5964 5.01304 10.6667 4.84347 10.6667 4.66666C10.6667 4.48985 10.5964 4.32028 10.4714 4.19526C10.3464 4.07023 10.1768 3.99999 10 3.99999H6C5.82319 3.99999 5.65362 4.07023 5.5286 4.19526C5.40357 4.32028 5.33333 4.48985 5.33333 4.66666C5.33333 4.84347 5.40357 5.01304 5.5286 5.13807C5.65362 5.26309 5.82319 5.33333 6 5.33333ZM6.31333 2.99999C6.32316 3.0813 6.36257 3.15614 6.42405 3.21024C6.48553 3.26434 6.56477 3.29392 6.64667 3.29333H9.33333C9.41483 3.2925 9.49331 3.26243 9.5545 3.20859C9.61568 3.15475 9.65549 3.08072 9.66667 2.99999C9.81326 2.29135 10.0841 1.61425 10.4667 0.999995C10.502 0.940405 10.5166 0.870792 10.5081 0.802038C10.4997 0.733285 10.4687 0.669267 10.42 0.619995C10.3798 0.567031 10.3247 0.527303 10.2617 0.505919C10.1987 0.484535 10.1308 0.482472 10.0667 0.499995L8.82667 1.03333C8.80588 1.04337 8.78309 1.04858 8.76 1.04858C8.73691 1.04858 8.71412 1.04337 8.69333 1.03333C8.65198 1.01793 8.61841 0.986767 8.6 0.946661L8.30667 0.206661C8.28105 0.146531 8.23832 0.0952587 8.1838 0.0592201C8.12928 0.0231815 8.06536 0.00396729 8 0.00396729C7.93464 0.00396729 7.87073 0.0231815 7.8162 0.0592201C7.76168 0.0952587 7.71895 0.146531 7.69333 0.206661L7.4 0.946661C7.38159 0.986767 7.34802 1.01793 7.30667 1.03333C7.28588 1.04337 7.26309 1.04858 7.24 1.04858C7.21691 1.04858 7.19412 1.04337 7.17333 1.03333L5.93333 0.499995C5.86975 0.474275 5.79978 0.468797 5.73297 0.484307C5.66615 0.499817 5.60575 0.53556 5.56 0.586661C5.51131 0.635934 5.48032 0.699951 5.47188 0.768705C5.46344 0.837458 5.47801 0.907072 5.51333 0.966661C5.89956 1.59109 6.17052 2.2798 6.31333 2.99999ZM10.2933 6.07999C10.2246 6.02717 10.14 5.999 10.0533 5.99999H5.94667C5.85996 5.999 5.77543 6.02717 5.70667 6.07999C4.00667 7.41333 2.10667 9.68 2.10667 11.68C2.10667 14.5 3.68 16 8 16C12.32 16 13.8933 14.5 13.8933 11.68C13.8933 9.68 12 7.37999 10.2933 6.07999ZM8.66667 13.42C8.6278 13.4276 8.59272 13.4483 8.56724 13.4786C8.54177 13.5089 8.52745 13.5471 8.52667 13.5867V13.8333C8.52667 13.9659 8.47399 14.0931 8.38022 14.1869C8.28645 14.2807 8.15928 14.3333 8.02667 14.3333C7.89406 14.3333 7.76688 14.2807 7.67311 14.1869C7.57935 14.0931 7.52667 13.9659 7.52667 13.8333V13.62C7.52667 13.5758 7.50911 13.5334 7.47785 13.5021C7.4466 13.4709 7.4042 13.4533 7.36 13.4533H6.96667C6.83406 13.4533 6.70688 13.4007 6.61311 13.3069C6.51935 13.2131 6.46667 13.0859 6.46667 12.9533C6.46667 12.8207 6.51935 12.6935 6.61311 12.5998C6.70688 12.506 6.83406 12.4533 6.96667 12.4533H8.4C8.50641 12.457 8.61062 12.4225 8.69387 12.3561C8.77711 12.2898 8.8339 12.1958 8.85401 12.0913C8.87411 11.9867 8.85621 11.8784 8.80353 11.7859C8.75084 11.6934 8.66684 11.6227 8.56667 11.5867L7.11333 11.0067C6.82042 10.8969 6.57119 10.6948 6.40334 10.4309C6.23548 10.167 6.15814 9.85554 6.18299 9.54374C6.20785 9.23193 6.33355 8.9367 6.54109 8.70268C6.74864 8.46867 7.02673 8.30859 7.33333 8.24666C7.3722 8.23905 7.40729 8.21837 7.43276 8.18804C7.45823 8.15772 7.47255 8.11959 7.47333 8.07999V7.83333C7.47333 7.70072 7.52601 7.57354 7.61978 7.47977C7.71355 7.38601 7.84073 7.33333 7.97333 7.33333C8.10594 7.33333 8.23312 7.38601 8.32689 7.47977C8.42065 7.57354 8.47333 7.70072 8.47333 7.83333V8.04666C8.47333 8.09086 8.49089 8.13326 8.52215 8.16451C8.5534 8.19577 8.5958 8.21333 8.64 8.21333H9.03333C9.16594 8.21333 9.29312 8.26601 9.38689 8.35977C9.48066 8.45354 9.53333 8.58072 9.53333 8.71333C9.53333 8.84594 9.48066 8.97311 9.38689 9.06688C9.29312 9.16065 9.16594 9.21333 9.03333 9.21333H7.62667C7.52026 9.20966 7.41604 9.24413 7.3328 9.31051C7.24956 9.37689 7.19277 9.47082 7.17266 9.57538C7.15255 9.67993 7.17046 9.78823 7.22314 9.88075C7.27582 9.97327 7.35982 10.0439 7.46 10.08L8.91333 10.66C9.20616 10.7719 9.45446 10.9764 9.62052 11.2423C9.78658 11.5082 9.86133 11.821 9.83343 12.1332C9.80552 12.4455 9.67648 12.7401 9.4659 12.9723C9.25532 13.2046 8.9747 13.3618 8.66667 13.42Z" fill="#F27900"/>
                            </svg>
                            <div class="breakdown-item-text">
                                <span class="label">Financial Health:</span>
                                <span class="score"> {result['breakdown']['financial']}/25</span>
                            </div>
                        </div>
                        <div class="breakdown-item">
                            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path fill-rule="evenodd" clip-rule="evenodd" d="M13.343 3.95399C13.2093 4.00196 13.0647 4.01098 12.9261 3.98C12.7875 3.94902 12.6606 3.87931 12.56 3.77899L12.008 3.22599L7.811 7.42299C7.74135 7.49269 7.65865 7.54798 7.56762 7.5857C7.4766 7.62342 7.37903 7.64283 7.2805 7.64283C7.18197 7.64283 7.0844 7.62342 6.99338 7.5857C6.90235 7.54798 6.81965 7.49269 6.75 7.42299L5.149 5.82199L1.335 9.63599C1.26578 9.70759 1.183 9.76469 1.09148 9.80395C0.999954 9.84321 0.90153 9.86386 0.801945 9.86468C0.702361 9.86549 0.60361 9.84647 0.511456 9.80872C0.419302 9.77096 0.33559 9.71523 0.265204 9.64478C0.194818 9.57433 0.139168 9.49056 0.101501 9.39837C0.0638333 9.30618 0.0449035 9.20742 0.0458154 9.10783C0.0467274 9.00825 0.067463 8.90984 0.106812 8.81836C0.146162 8.72688 0.203337 8.64415 0.275001 8.57499L4.617 4.22999C4.68665 4.1603 4.76935 4.10501 4.86038 4.06729C4.9514 4.02957 5.04897 4.01015 5.1475 4.01015C5.24603 4.01015 5.3436 4.02957 5.43462 4.06729C5.52565 4.10501 5.60835 4.1603 5.678 4.22999L7.28 5.83199L10.947 2.16499L10.395 1.61299C10.2945 1.5126 10.2245 1.38572 10.1933 1.24712C10.1621 1.10852 10.1709 0.963911 10.2187 0.830117C10.2665 0.696322 10.3513 0.578849 10.4632 0.491372C10.5751 0.403895 10.7096 0.350011 10.851 0.335994C11.764 0.245994 12.289 0.245994 13.168 0.335994C13.3395 0.353731 13.4997 0.430045 13.6216 0.552083C13.7434 0.67412 13.8195 0.834424 13.837 1.00599C13.928 1.88399 13.927 2.40999 13.837 3.32199C13.8229 3.4633 13.769 3.59771 13.6816 3.70959C13.5941 3.82147 13.4767 3.90622 13.343 3.95399ZM11.72 5.46199C11.8333 5.35212 11.9784 5.28079 12.1346 5.25817C12.2908 5.23555 12.4502 5.26278 12.59 5.33599L13.562 5.84599C13.6878 5.91219 13.7921 6.01275 13.863 6.13597C13.9338 6.25919 13.9681 6.4 13.962 6.54199L13.686 13.13C13.678 13.3235 13.5955 13.5064 13.4557 13.6404C13.3159 13.7744 13.1297 13.8492 12.936 13.849H10.964C10.8977 13.849 10.8341 13.8227 10.7872 13.7758C10.7403 13.7289 10.714 13.6653 10.714 13.599V6.54299C10.7139 6.50943 10.7206 6.47619 10.7337 6.44526C10.7467 6.41434 10.7659 6.38636 10.79 6.36299L11.72 5.46199ZM9.464 13.599C9.464 13.6653 9.43766 13.7289 9.39078 13.7758C9.34389 13.8227 9.2803 13.849 9.214 13.849H5.464C5.3977 13.849 5.33411 13.8227 5.28722 13.7758C5.24034 13.7289 5.214 13.6653 5.214 13.599V7.78499C5.214 7.76499 5.229 7.74899 5.249 7.75099C5.412 7.75899 5.572 7.82099 5.704 7.93599L7.349 9.37999C7.39617 9.42151 7.45725 9.44374 7.52006 9.44225C7.58288 9.44077 7.64284 9.41569 7.688 9.37199L9.04 8.05999C9.0753 8.02578 9.11989 8.00273 9.16822 7.99373C9.21654 7.98473 9.26645 7.99017 9.3117 8.00938C9.35694 8.02859 9.39552 8.06071 9.42261 8.10173C9.4497 8.14275 9.4641 8.19084 9.464 8.23999V13.599ZM3.535 9.13599L0.425001 12.312C0.287359 12.4521 0.210163 12.6406 0.210001 12.837V13.099C0.210001 13.513 0.546001 13.849 0.960001 13.849H3.714C3.78031 13.849 3.84389 13.8227 3.89078 13.7758C3.93766 13.7289 3.964 13.6653 3.964 13.599V9.31099C3.9641 9.26124 3.94934 9.21259 3.92163 9.17126C3.89391 9.12994 3.8545 9.09783 3.80843 9.07904C3.76236 9.06024 3.71173 9.05562 3.66302 9.06577C3.61431 9.07592 3.56974 9.10037 3.535 9.13599Z" fill="#F27900"/>
                            </svg>
                            <div class="breakdown-item-text">
                                <span class="label">Growth Readiness:</span>
                                <span class="score"> {result['breakdown']['growth']}/25</span>
                            </div>
                        </div>
                        <div class="breakdown-item">
                            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M14 12.6667C14.1699 12.6669 14.3334 12.7319 14.4569 12.8486C14.5805 12.9652 14.6548 13.1247 14.6648 13.2943C14.6747 13.4639 14.6196 13.6309 14.5105 13.7612C14.4014 13.8915 14.2467 13.9753 14.078 13.9954L14 14H2C1.83008 13.9998 1.66665 13.9348 1.54309 13.8181C1.41953 13.7015 1.34518 13.5421 1.33522 13.3724C1.32526 13.2028 1.38045 13.0358 1.48951 12.9055C1.59857 12.7752 1.75327 12.6914 1.922 12.6714L2 12.6667H14ZM12.6667 2.66669C13.0031 2.66658 13.327 2.79362 13.5737 3.02235C13.8204 3.25108 13.9714 3.56458 13.9967 3.90002L14 4.00002V10.6667C14.0001 11.0031 13.8731 11.3271 13.6443 11.5737C13.4156 11.8204 13.1021 11.9715 12.7667 11.9967L12.6667 12H3.33333C2.99695 12.0001 2.67296 11.8731 2.4263 11.6444C2.17965 11.4156 2.02856 11.1021 2.00333 10.7667L2 10.6667V4.00002C1.99989 3.66364 2.12694 3.33964 2.35566 3.09299C2.58439 2.84633 2.8979 2.69525 3.23333 2.67002L3.33333 2.66669H12.6667Z" fill="#F27900"/>
                            </svg>
                            <div class="breakdown-item-text">
                                <span class="label">Digital Maturity:</span>
                                <span class="score"> {result['breakdown']['digital']}/25</span>
                            </div>
                        </div>
                        <div class="breakdown-item">
                            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M6.5 0C6.10218 0 5.72065 0.158035 5.43934 0.43934C5.15804 0.720644 5 1.10218 5 1.5V2.804L3.87 2.152C3.52557 1.95341 3.11639 1.89969 2.73238 2.00263C2.34836 2.10557 2.02092 2.35676 1.822 2.701L0.322001 5.299C0.223358 5.46963 0.159309 5.65803 0.133515 5.85343C0.10772 6.04882 0.120687 6.24739 0.171672 6.43777C0.222658 6.62815 0.310663 6.80662 0.430658 6.96298C0.550653 7.11933 0.700285 7.2505 0.871001 7.349L2 8L0.870001 8.652C0.526102 8.85125 0.275339 9.17884 0.172779 9.56283C0.0702192 9.94682 0.124248 10.3558 0.323001 10.7L1.823 13.298C1.92141 13.4687 2.05248 13.6183 2.20872 13.7383C2.36496 13.8583 2.5433 13.9463 2.73358 13.9974C2.92385 14.0485 3.12232 14.0616 3.31765 14.0359C3.51298 14.0103 3.70135 13.9464 3.872 13.848L5 13.195V14.5C5 14.8978 5.15804 15.2794 5.43934 15.5607C5.72065 15.842 6.10218 16 6.5 16H9.5C9.89783 16 10.2794 15.842 10.5607 15.5607C10.842 15.2794 11 14.8978 11 14.5V13.196L12.13 13.848C12.4744 14.0466 12.8836 14.1003 13.2676 13.9974C13.6516 13.8944 13.9791 13.6432 14.178 13.299L15.678 10.701C15.7766 10.5304 15.8407 10.342 15.8665 10.1466C15.8923 9.95118 15.8793 9.75261 15.8283 9.56223C15.7773 9.37185 15.6893 9.19338 15.5693 9.03702C15.4493 8.88067 15.2997 8.7495 15.129 8.651L14 8L15.13 7.348C15.4743 7.14891 15.7255 6.82122 15.8283 6.43697C15.931 6.05273 15.877 5.6434 15.678 5.299L14.178 2.701C14.0796 2.53033 13.9485 2.38072 13.7923 2.26071C13.636 2.14071 13.4577 2.05265 13.2674 2.00158C13.0772 1.9505 12.8787 1.93741 12.6834 1.96305C12.488 1.98869 12.2996 2.05255 12.129 2.151L11 2.805V1.5C11 1.10218 10.842 0.720644 10.5607 0.43934C10.2794 0.158035 9.89783 0 9.5 0L6.5 0ZM8 10C7.46957 10 6.96086 9.78929 6.58579 9.41421C6.21071 9.03914 6 8.53043 6 8C6 7.46957 6.21071 6.96086 6.58579 6.58579C6.96086 6.21071 7.46957 6 8 6C8.53043 6 9.03914 6.21071 9.41421 6.58579C9.78929 6.96086 10 7.46957 10 8C10 8.53043 9.78929 9.03914 9.41421 9.41421C9.03914 9.78929 8.53043 10 8 10Z" fill="#F27900"/>
                            </svg>
                            <div class="breakdown-item-text">
                                <span class="label">Operational Efficiency:</span>
                                <span class="score"> {result['breakdown']['operations']}/25</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Additional Information -->
                <section class="section">
                    <p>
                        Your detailed assessment report is attached as a PDF with personalized recommendations and next steps.
                    </p>
                </section>

                <!-- What's Next Section -->
                <section class="section">
                    <h2 class="section-title">What's Next?</h2>
                </section>

                <section class="section">
                    <p>
                        Ready to transform these insights into growth? Our team specializes in helping {form_data.industry.lower()} businesses like yours overcome challenges like "{form_data.pain_point.lower()}" and achieve sustainable growth.
                    </p>
                </section>

                <!-- CTA Button -->
                <a href="https://calendly.com/beamxsolutions" class="cta-button">
                    <span>Schedule Your Free Consultation</span>
                </a>

                <!-- Footer -->
                <footer class="footer">
                    <div class="social-section">
                        <p>Follow us on</p>
                        <nav class="social-icons">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M18 2H15C13.6739 2 12.4021 2.52678 11.4645 3.46447C10.5268 4.40215 10 5.67392 10 7V10H7V14H10V22H14V14H17L18 10H14V7C14 6.73478 14.1054 6.48043 14.2929 6.29289C14.4804 6.10536 14.7348 6 15 6H18V2Z" stroke="#F5F5F5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M17 2H7C4.23858 2 2 4.23858 2 7V17C2 19.7614 4.23858 22 7 22H17C19.7614 22 22 19.7614 22 17V7C22 4.23858 19.7614 2 17 2Z" stroke="#F5F5F5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M16 11.37C16.1234 12.2022 15.9813 13.0522 15.5938 13.799C15.2063 14.5458 14.5932 15.1514 13.8416 15.5297C13.0901 15.9079 12.2385 16.0396 11.4078 15.9059C10.5771 15.7723 9.80977 15.3801 9.21485 14.7852C8.61993 14.1902 8.22774 13.4229 8.09408 12.5922C7.96042 11.7615 8.09208 10.9099 8.47034 10.1584C8.8486 9.40685 9.4542 8.79374 10.201 8.40624C10.9478 8.01874 11.7978 7.87658 12.63 8C13.4789 8.12588 14.2649 8.52146 14.8717 9.1283C15.4785 9.73515 15.8741 10.5211 16 11.37Z" stroke="#F5F5F5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M17.5 6.5H17.51" stroke="#F5F5F5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M23 2.99998C22.0424 3.67546 20.9821 4.19209 19.86 4.52999C19.2577 3.8375 18.4573 3.34668 17.567 3.12391C16.6767 2.90115 15.7395 2.95718 14.8821 3.28444C14.0247 3.6117 13.2884 4.19439 12.773 4.9537C12.2575 5.71302 11.9877 6.61232 12 7.52998V8.52998C10.2426 8.57555 8.50127 8.1858 6.93101 7.39543C5.36074 6.60506 4.01032 5.43862 3 3.99998C3 3.99998 -1 13 8 17C5.94053 18.398 3.48716 19.0989 1 19C10 24 21 19 21 7.49998C20.9991 7.22144 20.9723 6.94358 20.92 6.66999C21.9406 5.66348 22.6608 4.3927 23 2.99998Z" stroke="#F5F5F5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M16 8C17.5913 8 19.1174 8.63214 20.2426 9.75736C21.3679 10.8826 22 12.4087 22 14V21H18V14C18 13.4696 17.7893 12.9609 17.4142 12.5858C17.0391 12.2107 16.5304 12 16 12C15.4696 12 14.9609 12.2107 14.5858 12.5858C14.2107 12.9609 14 13.4696 14 14V21H10V14C10 12.4087 10.6321 10.8826 11.7574 9.75736C12.8826 8.63214 14.4087 8 16 8V8Z" stroke="#F5F5F5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M6 9H2V21H6V9Z" stroke="#F5F5F5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M4 6C5.10457 6 6 5.10457 6 4C6 2.89543 5.10457 2 4 2C2.89543 2 2 2.89543 2 4C2 5.10457 2.89543 6 4 6Z" stroke="#F5F5F5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </nav>
                    </div>

                    <div>
                        <p class="footer-text">www.beamxsolutions.com</p>
                    </div>

                    <p class="footer-description">
                        This email was generated from your business assessment at 
                        <a href="http://beamxsolutions.com/tools/business-assessment" class="footer-link" target="_blank" rel="noopener noreferrer">
                            beamxsolutions.com/tools/business-assessment
                        </a>
                    </p>

                    <p class="copyright">Copyright © 2025 BeamXSolutions</p>
                </footer>
            </div>
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

        Contact Us:
        Website: https://beamxsolutions.com
        Email: info@beamxsolutions.com
        Schedule a consultation: https://calendly.com/beamxsolutions

        Best regards,
        The BeamX Solutions Team

        ---
        This email was generated from your business assessment at https://beamxsolutions.com/business-assessment
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