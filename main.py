from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from typing import Dict, Literal, Optional
import datetime
import os
import base64
import io
from openai import OpenAI
from supabase import create_client, Client
import resend
import logging
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Business Scorecard API", version="2.1.0")

# CORS configuration
origins = [
    "https://beamxsolutions.com",
    "http://localhost:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI client
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")
try:
    client = OpenAI(api_key=openai_api_key)
    logger.info("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    raise ValueError(f"Failed to initialize OpenAI client: {e}")

# Initialize Supabase client
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
from_email = os.getenv("FROM_EMAIL", "noreply@beamxsolutions.com")
if not resend_api_key:
    logger.warning("Resend API key not configured. Email functionality will be disabled.")
else:
    resend.api_key = resend_api_key
    logger.info("Resend client initialized successfully")

# Pydantic models
class ScorecardInput(BaseModel):
    revenue: Literal["Under $10K", "$10K–$50K", "$50K–$250K", "$250K–$1M", "Over $1M"]
    profit_margin_known: Literal["Yes", "No"]
    monthly_expenses: Literal["Unknown", "≤$500", "$500–$1K", "$1K–$5K", "$5K–$20K", "$20K+"]
    cac_tracked: Literal["Yes", "No"]
    retention_rate: Literal["<10%", "10–25%", "25–50%", "50–75%", "75%+"]
    digital_campaigns: Literal["No", "Sometimes", "Consistently"]
    analytics_tools: Literal["No", "Basic tools (Excel, etc.)", "Advanced or custom dashboards"]
    crm_used: Literal["Yes", "No"]
    data_mgmt: Literal["Scattered or manual", "Somewhat structured", "Centralized and automated"]
    sops_doc: Literal["No", "Somewhat", "Fully documented"]
    team_size: Literal["1 (solo)", "2–4", "5–10", "11–50", "50+"]
    pain_point: Literal["Not growing", "Systems are chaotic", "Don't know what to optimize",
                        "Need to reduce cost", "Need funding", "Need more clients/customers",
                        "Growing fast, need structure"]
    industry: str = Field(..., min_length=1, max_length=100)

class EmailRequest(BaseModel):
    email: EmailStr
    result: Dict
    formData: ScorecardInput

def calculate_circle_progress(score: int, max_score: int = 100) -> tuple:
    """Calculate SVG circle progress values"""
    radius = 70
    circumference = 2 * 3.14159 * radius
    progress = (score / max_score) * circumference
    return circumference, progress

def parse_advisory_sections(advisory: str) -> Dict[str, list]:
    """Parse advisory text into structured sections"""
    sections = {"insights": [], "actions": []}
    current_section = None
    current_text = []
   
    lines = advisory.split('\n')
   
    for line in lines:
        line = line.strip()
        if not line:
            continue
           
        if '**Strategic Insights:**' in line or 'Strategic Insights:' in line:
            current_section = 'insights'
            continue
        elif '**Action Steps:**' in line or 'Action Steps:' in line:
            if current_text and current_section == 'insights':
                sections['insights'].append(' '.join(current_text))
                current_text = []
            current_section = 'actions'
            continue
       
        if line.startswith('•') or line.startswith('-'):
            if current_text and current_section:
                sections[current_section].append(' '.join(current_text))
                current_text = []
            current_text.append(line.lstrip('•-').strip())
        elif current_text:
            current_text.append(line)
   
    if current_text and current_section:
        sections[current_section].append(' '.join(current_text))
   
    def split_into_pairs(items):
        pairs = []
        for i in range(0, len(items), 2):
            pair = items[i:i+2]
            pairs.append(pair)
        return pairs
   
    result = {
        'insights': split_into_pairs(sections['insights']),
        'actions': split_into_pairs(sections['actions'])
    }
    
    logger.info(f"Parsed advisory sections - Insights: {len(sections['insights'])}, Actions: {len(sections['actions'])}")
    return result

def generate_pdf_report(result: Dict, form_data: ScorecardInput) -> io.BytesIO:
    """Generate PDF report using direct image URLs"""
   
    # Use direct image URLs
    logo_url = 'https://beamxsolutions.com/Beamx-Logo-Colour.png'
    cover_bg_url = 'https://beamxsolutions.com/front-background.jpg'
    cta_img_url = 'https://beamxsolutions.com/cta-image.jpg'
   
    # Parse advisory into sections
    advisory_sections = parse_advisory_sections(result.get('advisory', ''))
    logger.info(f"Advisory sections parsed - Insights pairs: {len(advisory_sections['insights'])}, Actions pairs: {len(advisory_sections['actions'])}")
   
    # Calculate circle progress
    total_score = result['total_score']
    circumference, progress = calculate_circle_progress(total_score)
    financial_pct = int((result['breakdown']['financial'] / 25) * 100)
    growth_pct = int((result['breakdown']['growth'] / 25) * 100)
    digital_pct = int((result['breakdown']['digital'] / 25) * 100)
    operations_pct = int((result['breakdown']['operations'] / 25) * 100)
   
    # Generate date
    generated_date = datetime.datetime.now().strftime('%B %d, %Y')
   
    # Build insights grid HTML
    insights_html = ""
    if advisory_sections['insights']:
        for pair in advisory_sections['insights']:
            insights_html += '<div class="insight-row">'
            for insight in pair:
                insights_html += f'<div class="insight-card"><p>{insight}</p></div>'
            insights_html += '</div>'
    else:
        insights_html = '<div class="insight-row"><div class="insight-card"><p>No strategic insights available.</p></div></div>'
    
    logger.info(f"Generated insights HTML with {len(advisory_sections['insights'])} pairs")
   
    # Build actions grid HTML
    actions_html = ""
    if advisory_sections['actions']:
        for pair in advisory_sections['actions']:
            actions_html += '<div class="action-row">'
            for action in pair:
                actions_html += f'<div class="action-card"><p>{action}</p></div>'
            actions_html += '</div>'
    else:
        actions_html = '<div class="action-row"><div class="action-card"><p>No action steps available.</p></div></div>'
    
    logger.info(f"Generated actions HTML with {len(advisory_sections['actions'])} pairs")
   
    html_content = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: letter;
                margin: 0;
            }}
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            body {{
                font-family: Arial, sans-serif;
                background: #f5f5f5;
                color: #000;
            }}
            .page {{
                width: 8.5in;
                height: 11in;
                background: white;
                position: relative;
                page-break-after: always;
            }}
            
            /* COVER PAGE */
            .page-cover {{
                background-image: url('{cover_bg_url}');
                background-size: cover;
                background-position: center;
                background-repeat: no-repeat;
                color: white;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }}
            .logo-section {{
                padding: 40px 60px;
            }}
            .logo-img {{
                width: 180px;
                height: auto;
            }}
            .title-section {{
                background: rgba(0, 51, 153, 0.95);
                padding: 80px 60px;
                text-align: left;
            }}
            .cover-title {{
                font-size: 72px;
                font-weight: bold;
                line-height: 1.1;
                color: white;
                margin: 0;
            }}
            .cover-footer {{
                padding: 40px 60px;
                color: white;
            }}
            .prepared-label, .generated-label {{
                font-size: 16px;
                font-weight: 600;
                margin: 0 0 5px 0;
            }}
            .prepared-name, .generated-date {{
                font-size: 18px;
                margin: 0 0 20px 0;
            }}
            
            /* CONTENT PAGES */
            .page-content {{
                background: #f5f5f5;
                padding: 40px 50px 70px;
            }}
            .executive-summary-box {{
                background: white;
                border: 3px solid #0066cc;
                padding: 30px;
                margin: 0 0 30px 0;
            }}
            .section-title {{
                color: #0066cc;
                font-size: 28px;
                font-weight: bold;
                margin: 0 0 20px 0;
                padding-bottom: 8px;
                border-bottom: 4px solid #0066cc;
                display: inline-block;
            }}
            .summary-icons {{
                display: flex;
                justify-content: space-between;
                margin: 25px 0 0 0;
                gap: 15px;
            }}
            .icon-item {{
                text-align: center;
                flex: 1;
            }}
            .icon-circle {{
                width: 70px;
                height: 70px;
                border: 3px solid #FF8C00;
                border-radius: 50%;
                margin: 0 auto 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 28px;
            }}
            .icon-label {{
                color: #FF8C00;
                font-size: 15px;
                font-weight: 600;
                margin: 0 0 6px 0;
            }}
            .icon-value {{
                color: #000;
                font-size: 16px;
                font-weight: 700;
                margin: 0;
            }}
            .assessment-container {{
                display: flex;
                align-items: center;
                gap: 40px;
                margin: 20px 0 30px 0;
                background: white;
                padding: 30px;
            }}
            .chart-section {{
                flex-shrink: 0;
            }}
            .maturity-level {{
                font-size: 20px;
                font-weight: 600;
                margin: 0;
            }}
            .score-table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0 0 0;
                background: white;
            }}
            .score-table thead {{
                background: #FF8C00;
                color: white;
            }}
            .score-table th {{
                padding: 12px 18px;
                text-align: center;
                border: 1px solid #FF8C00;
                font-weight: 700;
                font-size: 16px;
            }}
            .score-table td {{
                padding: 12px 18px;
                text-align: center;
                border: 1px solid #ddd;
                font-size: 15px;
            }}
            .score-table tbody tr:nth-child(even) {{
                background: #f9f9f9;
            }}
            .page-footer {{
                position: absolute;
                bottom: 0;
                left: 0;
                right: 0;
                background: #0066cc;
                color: white;
                padding: 12px 50px;
                display: flex;
                justify-content: space-between;
                font-size: 14px;
            }}
            .subsection-title {{
                color: #FF8C00;
                font-size: 22px;
                font-weight: bold;
                text-align: center;
                margin: 25px 0 20px 0;
            }}
            .insight-row, .action-row {{
                display: flex;
                gap: 20px;
                margin: 0 0 20px 0;
            }}
            .insight-card, .action-card {{
                background: white;
                padding: 25px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                flex: 1;
                margin: 0;
            }}
            .insight-card p, .action-card p {{
                line-height: 1.6;
                color: #333;
                font-size: 15px;
                margin: 0;
            }}
            
            /* CTA PAGE */
            .page-cta {{
                background: #0066cc;
                color: white;
                padding: 50px 60px;
            }}
            .cta-title {{
                font-size: 38px;
                font-weight: bold;
                margin: 0 0 25px 0;
                padding-bottom: 10px;
                border-bottom: 4px solid #FF8C00;
                display: inline-block;
            }}
            .cta-text-box {{
                background: white;
                color: #333;
                padding: 20px;
                border-radius: 8px;
                margin: 0 0 25px 0;
                font-size: 16px;
                line-height: 1.6;
            }}
            .cta-text-box p {{
                margin: 0;
            }}
            .cta-image-box {{
                margin: 0 0 30px 0;
            }}
            .cta-image {{
                width: 100%;
                max-width: 100%;
                height: 350px;
                object-fit: cover;
                border-radius: 8px;
                display: block;
            }}
            .contact-info {{
                margin: 30px 0 0 0;
            }}
            .contact-item {{
                display: flex;
                align-items: center;
                margin: 0 0 18px 0;
                font-size: 16px;
            }}
            .contact-icon {{
                margin-right: 12px;
                font-size: 20px;
            }}
        </style>
    </head>
    <body>
        <!-- COVER PAGE -->
        <div class="page page-cover">
            <div class="logo-section">
                <img src="{logo_url}" alt="BeamX Solutions" class="logo-img" />
            </div>
            <div class="title-section">
                <h1 class="cover-title">Business<br>Assessment<br>Report</h1>
            </div>
            <div class="cover-footer">
                <div class="prepared-by">
                    <p class="prepared-label">Prepared By</p>
                    <p class="prepared-name">BeamX Solutions</p>
                </div>
                <div class="generated-on">
                    <p class="generated-label">Generated on</p>
                    <p class="generated-date">{generated_date}</p>
                </div>
            </div>
        </div>

        <!-- PAGE 2: EXECUTIVE SUMMARY & OVERALL ASSESSMENT -->
        <div class="page page-content">
            <div class="executive-summary-box">
                <h2 class="section-title">Executive Summary</h2>
                <div class="summary-icons">
                    <div class="icon-item">
                        <div class="icon-circle">📊</div>
                        <p class="icon-label">Industry</p>
                        <p class="icon-value">{form_data.industry}</p>
                    </div>
                    <div class="icon-item">
                        <div class="icon-circle">👥</div>
                        <p class="icon-label">Team Size</p>
                        <p class="icon-value">{form_data.team_size}</p>
                    </div>
                    <div class="icon-item">
                        <div class="icon-circle">💰</div>
                        <p class="icon-label">Annual Revenue</p>
                        <p class="icon-value">{form_data.revenue}</p>
                    </div>
                    <div class="icon-item">
                        <div class="icon-circle">🎯</div>
                        <p class="icon-label">Primary Pain Point</p>
                        <p class="icon-value">{form_data.pain_point}</p>
                    </div>
                </div>
            </div>

            <h2 class="section-title">Overall Assessment</h2>
            <div class="assessment-container">
                <div class="chart-section">
                    <svg width="200" height="200" viewBox="0 0 200 200">
                        <circle cx="100" cy="100" r="70" fill="none" stroke="#e0e0e0" stroke-width="30"/>
                        <circle cx="100" cy="100" r="70" fill="none" stroke="#0066cc" stroke-width="30"
                                stroke-dasharray="{progress} {circumference}" stroke-dashoffset="0"
                                transform="rotate(-90 100 100)"/>
                        <text x="100" y="110" text-anchor="middle" font-size="30" font-weight="bold" fill="#000">
                            {total_score}/100
                        </text>
                    </svg>
                </div>
                <div class="maturity-level">
                    <p>Business Maturity Level: {result['label']}</p>
                </div>
            </div>

            <h2 class="section-title">Detailed Score Breakdown</h2>
            <table class="score-table">
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Your Score</th>
                        <th>Max Score</th>
                        <th>Percentage</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Financial Health</td>
                        <td>{result['breakdown']['financial']}</td>
                        <td>25</td>
                        <td>{financial_pct}%</td>
                    </tr>
                    <tr>
                        <td>Growth Readiness</td>
                        <td>{result['breakdown']['growth']}</td>
                        <td>25</td>
                        <td>{growth_pct}%</td>
                    </tr>
                    <tr>
                        <td>Digital Maturity</td>
                        <td>{result['breakdown']['digital']}</td>
                        <td>25</td>
                        <td>{digital_pct}%</td>
                    </tr>
                    <tr>
                        <td>Operational Efficiency</td>
                        <td>{result['breakdown']['operations']}</td>
                        <td>25</td>
                        <td>{operations_pct}%</td>
                    </tr>
                </tbody>
            </table>

            <div class="page-footer">
                <div>Business Assessment Report</div>
                <div>Copyright © 2025 BeamXSolutions</div>
            </div>
        </div>

        <!-- PAGE 3: STRATEGIC ADVISORY -->
        <div class="page page-content">
            <h2 class="section-title">Strategic Advisory & Recommendations</h2>
            <h3 class="subsection-title">Strategic Insights</h3>
            {insights_html}
            <h3 class="subsection-title">Action Steps</h3>
            {actions_html}
            <div class="page-footer">
                <div>Business Assessment Report</div>
                <div>Copyright © 2025 BeamXSolutions</div>
            </div>
        </div>

        <!-- PAGE 4: CTA -->
        <div class="page page-cta">
            <h2 class="cta-title">Ready to Take Action?</h2>
            <div class="cta-text-box">
                <p>Based on your assessment results, BeamX Solutions can help you implement the
                strategic recommendations outlined above. Our team specializes in helping
                {form_data.industry.lower()} businesses overcome challenges and achieve
                sustainable growth.</p>
            </div>
            <div class="cta-image-box">
                <img src="{cta_img_url}" alt="BeamX Solutions Team" class="cta-image" />
            </div>
            <div class="contact-info">
                <div class="contact-item">
                    <span class="contact-icon">🌐</span>
                    <span>www.beamxsolutions.com</span>
                </div>
                <div class="contact-item">
                    <span class="contact-icon">✉️</span>
                    <span>info@beamxsolutions.com</span>
                </div>
                <div class="contact-item">
                    <span class="contact-icon">📅</span>
                    <span>https://calendly.com/beamxsolutions</span>
                </div>
            </div>
        </div>
    </body>
    </html>
    '''
   
    # Generate PDF from HTML using WeasyPrint
    buffer = io.BytesIO()
   
    try:
        font_config = FontConfiguration()
        HTML(string=html_content).write_pdf(buffer, font_config=font_config)
        buffer.seek(0)
        logger.info("PDF generated successfully using WeasyPrint")
        return buffer
    except Exception as e:
        logger.error(f"Error generating PDF with WeasyPrint: {e}")
        raise

# Scoring functions
def score_financial_health(data: ScorecardInput) -> int:
    revenue_map = {"Under $10K": 1, "$10K–$50K": 2, "$50K–$250K": 3, "$250K–$1M": 4, "Over $1M": 5}
    expenses_map = {"Unknown": 1, "≤$500": 2, "$500–$1K": 3, "$1K–$5K": 4, "$5K–$20K": 5, "$20K+": 6}
    total_score = revenue_map[data.revenue] + (1 if data.profit_margin_known == "Yes" else 0) + expenses_map[data.monthly_expenses]
    return round((total_score / 12) * 25)

def score_growth_readiness(data: ScorecardInput) -> int:
    retention_map = {"<10%": 1, "10–25%": 2, "25–50%": 3, "50–75%": 4, "75%+": 5}
    campaign_map = {"No": 1, "Sometimes": 3, "Consistently": 5}
    total_score = (1 if data.cac_tracked == "Yes" else 0) + retention_map[data.retention_rate] + campaign_map[data.digital_campaigns]
    return round((total_score / 11) * 25)

def score_digital_maturity(data: ScorecardInput) -> int:
    analytics_map = {"No": 1, "Basic tools (Excel, etc.)": 3, "Advanced or custom dashboards": 5}
    data_map = {"Scattered or manual": 1, "Somewhat structured": 3, "Centralized and automated": 5}
    total_score = analytics_map[data.analytics_tools] + (1 if data.crm_used == "Yes" else 0) + data_map[data.data_mgmt]
    return round((total_score / 11) * 25)

def score_operational_efficiency(data: ScorecardInput) -> int:
    sop_map = {"No": 1, "Somewhat": 3, "Fully documented": 5}
    team_map = {"1 (solo)": 1, "2–4": 2, "5–10": 3, "11–50": 4, "50+": 5}
    pain_map = {"Not growing": 1, "Systems are chaotic": 2, "Don't know what to optimize": 3,
                "Need to reduce cost": 3, "Need funding": 4, "Need more clients/customers": 4,
                "Growing fast, need structure": 5}
    total_score = sop_map[data.sops_doc] + team_map[data.team_size] + pain_map[data.pain_point]
    return round((total_score / 15) * 25)

async def generate_gpt5_advisory(input_data: ScorecardInput, scores: Dict[str, int]) -> str:
    prompt = f"""Write a comprehensive growth advisory for a {input_data.industry} business with these scores:
    • Financial Health: {scores['financial']}/25
    • Growth Readiness: {scores['growth']}/25
    • Digital Maturity: {scores['digital']}/25
    • Operations Efficiency: {scores['operations']}/25
    Business Context:
    • Revenue: {input_data.revenue}
    • Team Size: {input_data.team_size}
    • Primary Pain Point: {input_data.pain_point}
    Provide response in this format:
    **Strategic Insights:**
    • [Insight 1]
    • [Insight 2]
    • [Insight 3]
    **Action Steps:**
    • [Step 1]
    • [Step 2]
    • [Step 3]
    NEVER use em dashes or hyphens for emphasis."""
    try:
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "You are an expert business growth advisor."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=400
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error calling GPT API: {e}")
        strongest = max(scores, key=scores.get)
        weakest = min(scores, key=scores.get)
        return f"""**Strategic Insights:**
        • Your {strongest} capabilities provide foundation for growth
        • {weakest} needs immediate attention
        • Focus on systematic improvements
        **Action Steps:**
        • Address {weakest} gap with tracking tools
        • Leverage {strongest} strength for momentum
        • Create 90 day improvement plan"""

def send_email_with_resend(recipient_email: str, result: Dict, form_data: ScorecardInput) -> bool:
    if not resend_api_key:
        return False
   
    try:
        email_logo_url = 'https://beamxsolutions.com/asset-1-2.png'
        pdf_buffer = generate_pdf_report(result, form_data)
        pdf_content = pdf_buffer.read()
        pdf_base64 = base64.b64encode(pdf_content).decode()
        
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
                                    <table cellpadding="0" cellspacing="0" align="center" style="margin: 0 auto 32px auto; text-align: center;">
                                        <tr>
                                            <!-- Facebook -->
                                            <td style="padding: 0 12px;">
                                                <a href="https://facebook.com/beamxsolutions" style="display: inline-block; text-decoration: none;">
                                                    <img src="https://beamxsolutions.com/facebook-img.png" alt="Facebook" width="24" height="24" style="display: block;">
                                                </a>
                                            </td>
                                            <!-- Instagram -->
                                            <td style="padding: 0 12px;">
                                                <a href="https://instagram.com/beamxsolutions" style="display: inline-block; text-decoration: none;">
                                                    <img src="https://beamxsolutions.com/instagram-img.png" alt="Instagram" width="24" height="24" style="display: block;">
                                                </a>
                                            </td>
                                            <!-- Twitter/X -->
                                            <td style="padding: 0 12px;">
                                                <a href="https://twitter.com/beamxsolutions" style="display: inline-block; text-decoration: none;">
                                                    <img src="https://beamxsolutions.com/twitter-img.png" alt="Twitter" width="24" height="24" style="display: block;">
                                                </a>
                                            </td>
                                            <!-- LinkedIn -->
                                            <td style="padding: 0 12px;">
                                                <a href="https://linkedin.com/company/beamxsolutions" style="display: inline-block; text-decoration: none;">
                                                    <img src="https://beamxsolutions.com/linkedin-img.png" alt="LinkedIn" width="24" height="24" style="display: block;">
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
        Best regards,
        The BeamX Solutions Team
        Copyright © 2025 BeamXSolutions
        """
       
        params = {
            "from": f"BeamX Solutions <{from_email}>",
            "to": [recipient_email],
            "subject": f"Your Business Assessment Results: {result['total_score']}/100 ({result['label']}) 📊",
            "html": html_content,
            "text": text_content,
            "attachments": [{"filename": "BeamX_Business_Assessment_Report.pdf", "content": pdf_base64}]
        }
       
        email_response = resend.Emails.send(params)
        logger.info(f"Email sent successfully to {recipient_email}, ID: {email_response.get('id', 'unknown')}")
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False

@app.post("/generate-report")
async def generate_report(input_data: ScorecardInput):
    try:
        financial_score = score_financial_health(input_data)
        growth_score = score_growth_readiness(input_data)
        digital_score = score_digital_maturity(input_data)
        operations_score = score_operational_efficiency(input_data)
        total_score = financial_score + growth_score + digital_score + operations_score
       
        if total_score >= 90:
            label = "Built for Scale"
        elif total_score >= 70:
            label = "Growth Ready"
        elif total_score >= 50:
            label = "Developing"
        else:
            label = "Early Stage"
       
        scores = {
            "financial": financial_score,
            "growth": growth_score,
            "digital": digital_score,
            "operations": operations_score
        }
        advisory = await generate_gpt5_advisory(input_data, scores)
       
        supabase.table("basic_assessments").insert({
            **input_data.dict(),
            "scores": scores,
            "total_score": total_score,
            "advisory": advisory,
            "generated_at": datetime.datetime.utcnow().isoformat()
        }).execute()
       
        return {
            "total_score": total_score,
            "label": label,
            "breakdown": scores,
            "advisory": advisory,
            "industry": input_data.industry
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/email-results")
async def email_results(email_request: EmailRequest):
    try:
        success = send_email_with_resend(email_request.email, email_request.result, email_request.formData)
        if success:
            return {"status": "success", "message": "Email sent successfully"}
        raise HTTPException(status_code=500, detail="Email send failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "model": "gpt-4-turbo", "version": "2.1.0"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)