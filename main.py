from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal
import openai
from fastapi.responses import JSONResponse
from datetime import datetime
import os

app = FastAPI()

# --- Secrets (Inject via Env or Config Management) ---
openai.api_key = os.getenv("OPENAI_API_KEY")

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
def score_financial_health(data):
    revenue_map = {"Under $10K": 1, "$10K–$50K": 2, "$50K–$250K": 3, "$250K–$1M": 4, "Over $1M": 5}
    burn_map = {"Unknown": 1, "≤$1K": 2, "$1K–$5K": 3, "$5K–$20K": 4, "$20K+": 5}
    try:
        score = revenue_map[data.revenue] + (1 if data.profit_margin_known == "Yes" else 0) + burn_map[data.monthly_burn]
        return round((score / 11) * 25)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Financial health scoring error: {str(e)}")

def score_growth_readiness(data):
    retention_map = {"<10%": 1, "10–25%": 2, "25–50%": 3, "50–75%": 4, "75%+": 5}
    campaign_map = {"No": 1, "Sometimes": 3, "Consistently": 5}
    try:
        score = (1 if data.cac_tracked == "Yes" else 0) + retention_map[data.retention_rate] + campaign_map[data.digital_campaigns]
        return round((score / 11) * 25)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Growth readiness scoring error: {str(e)}")

def score_digital_maturity(data):
    analytics_map = {"No": 1, "Basic tools (Excel, etc.)": 3, "Advanced or custom dashboards": 5}
    data_map = {"Scattered or manual": 1, "Somewhat structured": 3, "Centralized and automated": 5}
    try:
        score = analytics_map[data.analytics_tools] + (1 if data.crm_used == "Yes" else 0) + data_map[data.data_mgmt]
        return round((score / 11) * 25)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Digital maturity scoring error: {str(e)}")

def score_operational_efficiency(data):
    sop_map = {"No": 1, "Somewhat": 3, "Fully documented": 5}
    team_map = {"0 (solo)": 1, "1–3": 2, "4–10": 3, "11–50": 4, "50+": 5}
    pain_map = {"Not growing": 1, "Systems are chaotic": 2, "Don't know what to optimize": 3, "Need funding": 4, "Growing fast, need structure": 5}
    try:
        score = sop_map[data.sops_doc] + team_map[data.team_size] + pain_map[data.pain_point]
        return round((score / 11) * 25)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Operational efficiency scoring error: {str(e)}")

# --- GPT Insight Generator ---
def generate_insight(industry, f, g, d, o):
    prompt = f"""
    Write a growth advisory for a {industry} business with:
    Financial: {f}/25, Growth: {g}/25, Digital: {d}/25, Operations: {o}/25
    Use two smart paragraphs and include 2 practical action steps.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Insight generation error: {str(e)}")

# --- Main Endpoint ---
@app.post("/generate-report")
def generate_report(data: ScorecardInput):
    f_score = score_financial_health(data)
    g_score = score_growth_readiness(data)
    d_score = score_digital_maturity(data)
    o_score = score_operational_efficiency(data)
    total = f_score + g_score + d_score + o_score

    if total <= 40:
        label = "Foundation Stage"
    elif total <= 60:
        label = "Scaling Cautiously"
    elif total <= 80:
        label = "Growth Ready"
    else:
        label = "Built for Scale"

    insight = generate_insight(data.industry, f_score, g_score, d_score, o_score)

    return JSONResponse({
        "industry": data.industry,
        "scorecard": {
            "total": total,
            "label": label,
            "financial_health": f_score,
            "growth_readiness": g_score,
            "digital_maturity": d_score,
            "operational_efficiency": o_score
        },
        "insight": insight,
        "generated_at": datetime.utcnow().isoformat()
    })
