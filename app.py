from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal
import openai
import bleach
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4")
BEAMX_URL = os.getenv("BEAMX_URL", "https://beamxsolutions.netlify.app")

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://beamxsolutions.netlify.app"],  # Update with frontend URL in production
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)

# --- Input Schema ---
class ScorecardInput(BaseModel):
    revenue: Literal["Under $10K", "$10K–$50K", "$50K–$250K", "$250K–$1M", "Over $1M"]
    profit_margin_known: Literal["Yes", "No"]
    monthly_burn: Literal["Unknown", "≤$1K", "$1K–$5K", "$5K–$20K", "$20K+"]
    cac_tracked: Literal["Yes", "No"]
    retention_rate: Literal["<10%", "10–25%", "25–50%", "50–75%", "75%+"]
    digital_campaigns: Literal["No", "Sometimes", "Consistently"]
    analytics_tools: Literal["No", "Basic tools (Excel, etc.)", "Advanced or custom dashboards"]
    crm_used: Literal["Yes", "No"]
    data_mgmt: Literal["Scattered or manual", "Somewhat structured", "Centralized and automated"]
    sops_doc: Literal["No", "Somewhat", "Fully documented"]
    team_size: Literal["0 (solo)", "1–3", "4–10", "11–50", "50+"]
    pain_point: Literal["Not growing", "Systems are chaotic", "Don't know what to optimize", "Need funding", "Growing fast, need structure"]
    industry: str

# --- Scoring Functions ---
def score_financial_health(data: ScorecardInput) -> int:
    """Calculate financial health score (max 11)."""
    revenue_map = {"Under $10K": 1, "$10K–$50K": 2, "$50K–$250K": 3, "$250K–$1M": 4, "Over $1M": 5}
    burn_map = {"Unknown": 1, "≤$1K": 2, "$1K–$5K": 3, "$5K–$20K": 4, "$20K+": 5}
    score = revenue_map[data.revenue] + (1 if data.profit_margin_known == "Yes" else 0) + burn_map[data.monthly_burn]
    return round((score / 11) * 25)

def score_growth_readiness(data: ScorecardInput) -> int:
    """Calculate growth readiness score (max 11)."""
    retention_map = {"<10%": 1, "10–25%": 2, "25–50%": 3, "50–75%": 4, "75%+": 5}
    campaign_map = {"No": 1, "Sometimes": 3, "Consistently": 5}
    score = (1 if data.cac_tracked == "Yes" else 0) + retention_map[data.retention_rate] + campaign_map[data.digital_campaigns]
    return round((score / 11) * 25)

def score_digital_maturity(data: ScorecardInput) -> int:
    """Calculate digital maturity score (max 11)."""
    analytics_map = {"No": 1, "Basic tools (Excel, etc.)": 3, "Advanced or custom dashboards": 5}
    data_map = {"Scattered or manual": 1, "Somewhat structured": 3, "Centralized and automated": 5}
    score = analytics_map[data.analytics_tools] + (1 if data.crm_used == "Yes" else 0) + data_map[data.data_mgmt]
    return round((score / 11) * 25)

def score_operational_efficiency(data: ScorecardInput) -> int:
    """Calculate operational efficiency score (max 15, normalized to 11 for consistency)."""
    sop_map = {"No": 1, "Somewhat": 3, "Fully documented": 5}
    team_map = {"0 (solo)": 1, "1–3": 2, "4–10": 3, "11–50": 4, "50+": 5}
    pain_map = {"Not growing": 1, "Systems are chaotic": 2, "Don't know what to optimize": 3, "Need funding": 4, "Growing fast, need structure": 5}
    score = sop_map[data.sops_doc] + team_map[data.team_size] + pain_map[data.pain_point]
    # Normalize from max 15 to max 11
    return round((score / 15) * 11 * (25 / 11))

# --- GPT Insight Generator ---
async def generate_insight(industry: str, f: int, g: int, d: int, o: int) -> str:
    """Generate insights using OpenAI API."""
    prompt = f"""
    Write a growth advisory for a {industry} business with:
    Financial: {f}/25, Growth: {g}/25, Digital: {d}/25, Operations: {o}/25
    Use two smart paragraphs and include 2 practical action steps.
    """
    try:
        response = await openai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        return bleach.clean(response.choices[0].message.content.strip())
    except openai.OpenAIError as e:
        logger.error(f"OpenAI API error: {str(e)}")
        return "Unable to generate insights at this time. Please try again later."
    except Exception as e:
        logger.error(f"Unexpected error in generate_insight: {str(e)}")
        return "An unexpected error occurred. Please try again later."

# --- HTML Report Generator ---
def generate_html_report(score_total: int, label: str, insight: str, f: int, g: int, d: int, o: int, industry: str) -> str:
    """Generate HTML report content."""
    year = datetime.now().year
    sanitized_insight = bleach.clean(insight)
    sanitized_industry = bleach.clean(industry)
    return f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 30px; max-width: 800px; margin: 0 auto; }}
            h1 {{ color: #007bff; }}
            .highlight {{ font-weight: bold; color: #007bff; }}
            .cta {{ background: #f1f9ff; padding: 10px; border-left: 4px solid #007bff; margin-top: 20px; }}
            ul {{ margin: 20px 0; padding-left: 20px; }}
            p {{ line-height: 1.6; }}
        </style>
    </head>
    <body>
        <h1>BeamX Business Health Report</h1>
        <p><strong>Industry:</strong> {sanitized_industry}</p>
        <p><strong>Total Score:</strong> <span class='highlight'>{score_total}/100 – {label}</span></p>
        <ul>
            <li>Financial Health: {f}/25</li>
            <li>Growth Readiness: {g}/25</li>
            <li>Digital Maturity: {d}/25</li>
            <li>Operational Efficiency: {o}/25</li>
        </ul>
        <p>{sanitized_insight}</p>
        <div class='cta'>To turn these insights into action, visit <a href='{BEAMX_URL}'>BeamX Solutions</a></div>
        <p style='font-size:12px;'>© {year} BeamX Solutions</p>
    </body>
    </html>
    """

# --- Main Endpoint ---
@app.post("/generate-report")
async def generate_full_report(data: ScorecardInput):
    """Generate scorecard report and return as JSON."""
    try:
        f_score = score_financial_health(data)
        g_score = score_growth_readiness(data)
        d_score = score_digital_maturity(data)
        o_score = score_operational_efficiency(data)
        total = f_score + g_score + d_score + o_score

        if total < 0 or total > 100:
            logger.error(f"Invalid total score: {total}")
            raise HTTPException(status_code=500, detail="Internal error: Invalid score calculation")

        if total <= 40:
            label = "Foundation Stage"
        elif total <= 60:
            label = "Scaling Cautiously"
        elif total <= 80:
            label = "Growth Ready"
        else:
            label = "Built for Scale"

        insight = await generate_insight(data.industry, f_score, g_score, d_score, o_score)
        html_report = generate_html_report(total, label, insight, f_score, g_score, d_score, o_score, data.industry)

        return {
            "score": total,
            "label": label,
            "sub_scores": {
                "financial": f_score,
                "growth": g_score,
                "digital": d_score,
                "operations": o_score
            },
            "insights": insight,
            "html_report": html_report
        }
    except Exception as e:
        logger.error(f"Error in generate_full_report: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")