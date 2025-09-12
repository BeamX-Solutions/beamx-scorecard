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
        "≤$1K", 
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
    story.append(Paragraph("📞 Schedule a consultation: https://beamxsolutions.com/contact", styles['Normal']))
    
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
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #1f2937; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background-color: #f9f9f9; }}
                .score-box {{ background-color: #e5f3ff; padding: 15px; margin: 15px 0; border-radius: 5px; }}
                .breakdown {{ background-color: white; padding: 15px; margin: 10px 0; border-left: 4px solid #3b82f6; }}
                .footer {{ background-color: #1f2937; color: white; padding: 20px; text-align: center; }}
                .cta-button {{ 
                    display: inline-block; 
                    background-color: #3b82f6; 
                    color: white; 
                    padding: 12px 24px; 
                    text-decoration: none; 
                    border-radius: 5px; 
                    margin: 10px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Your Business Assessment Results</h1>
                    <p>BeamX Solutions</p>
                </div>
                
                <div class="content">
                    <p>Hello!</p>
                    
                    <p>Thank you for completing the BeamX Solutions Business Assessment. Your personalized results are ready!</p>
                    
                    <div class="score-box">
                        <h2>Your Overall Score: {result['total_score']}/100</h2>
                        <p><strong>Business Maturity Level: {result['label']}</strong></p>
                    </div>
                    
                    <h3>Score Breakdown:</h3>
                    <div class="breakdown">
                        <p><strong>💰 Financial Health:</strong> {result['breakdown']['financial']}/25</p>
                        <p><strong>📈 Growth Readiness:</strong> {result['breakdown']['growth']}/25</p>
                        <p><strong>💻 Digital Maturity:</strong> {result['breakdown']['digital']}/25</p>
                        <p><strong>⚙️ Operational Efficiency:</strong> {result['breakdown']['operations']}/25</p>
                    </div>
                    
                    <p>📄 <strong>Your detailed assessment report is attached as a PDF</strong> with personalized recommendations and next steps.</p>
                    
                    <h3>What's Next?</h3>
                    <p>Ready to transform these insights into growth? Our team specializes in helping {form_data.industry.lower()} businesses like yours overcome challenges like "{form_data.pain_point.lower()}" and achieve sustainable growth.</p>
                    
                    <div style="text-align: center;">
                        <a href="https://beamxsolutions.com/contact" class="cta-button">Schedule Your Free Consultation</a>
                    </div>
                </div>
                
                <div class="footer">
                    <p><strong>BeamX Solutions</strong></p>
                    <p>🌐 <a href="https://beamxsolutions.com" style="color: #60a5fa;">beamxsolutions.com</a></p>
                    <p>📧 info@beamxsolutions.com</p>
                    <hr style="border-color: #374151; margin: 20px 0;">
                    <p style="font-size: 12px;">This email was generated from your business assessment at beamxsolutions.com/business-assessment</p>
                </div>
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
        Schedule a consultation: https://beamxsolutions.com/contact

        Best regards,
        The BeamX Solutions Team

        ---
        This email was generated from your business assessment at https://beamxsolutions.com/business-assessment
        """
        
        # Send email using Resend
        params = {
            "from": from_email,
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
        "≤$1K": 2, 
        "$1K–$5K": 3, 
        "$5K–$20K": 4, 
        "$20K+": 5
    }
    
    revenue_score = revenue_map[data.revenue]
    profit_score = 1 if data.profit_margin_known == "Yes" else 0
    expenses_score = expenses_map[data.monthly_expenses]
    
    total_score = revenue_score + profit_score + expenses_score
    max_score = 5 + 1 + 5
    
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