from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict
import datetime
import os
import openai

app = FastAPI()

# CORS configuration
origins = [
    "https://beamxsolutions.com",  # frontend on Netlify
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up OpenAI API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")

class ScorecardInput(BaseModel):
    revenue: str
    profit_margin_known: str
    monthly_burn: str
    cac_tracked: str
    retention_rate: str
    digital_campaigns: str
    analytics_tools: str
    crm_used: str
    data_mgmt: str
    sops_doc: str
    team_size: str
    pain_point: str
    industry: str

# --- Scoring Functions ---
def score_financial_health(data):
    revenue_map = {"Under $10K": 1, "$10K–$50K": 2, "$50K–$250K": 3, "$250K–$1M": 4, "Over $1M": 5}
    burn_map = {"Unknown": 1, "≤$1K": 2, "$1K–$5K": 3, "$5K–$20K": 4, "$20K+": 5}
    score = revenue_map[data.revenue] + (1 if data.profit_margin_known == "Yes" else 0) + burn_map[data.monthly_burn]
    max_score = 5 + 1 + 5  # 11
    return round((score / max_score) * 25)

def score_growth_readiness(data):
    retention_map = {"<10%": 1, "10–25%": 2, "25–50%": 3, "50–75%": 4, "75%+": 5}
    campaign_map = {"No": 1, "Sometimes": 3, "Consistently": 5}
    score = (1 if data.cac_tracked == "Yes" else 0) + retention_map[data.retention_rate] + campaign_map[data.digital_campaigns]
    max_score = 1 + 5 + 5  # 11
    return round((score / max_score) * 25)

def score_digital_maturity(data):
    analytics_map = {"No": 1, "Basic tools (Excel, etc.)": 3, "Advanced or custom dashboards": 5}
    data_map = {"Scattered or manual": 1, "Somewhat structured": 3, "Centralized and automated": 5}
    score = analytics_map[data.analytics_tools] + (1 if data.crm_used == "Yes" else 0) + data_map[data.data_mgmt]
    max_score = 5 + 1 + 5  # 11
    return round((score / max_score) * 25)

def score_operational_efficiency(data):
    sop_map = {"No": 1, "Somewhat": 3, "Fully documented": 5}
    team_map = {"0 (solo)": 1, "1–3": 2, "4–10": 3, "11–50": 4, "50+": 5}
    pain_map = {
        "Not growing": 1, "Systems are chaotic": 2, "Don't know what to optimize": 3,
        "Need funding": 4, "Growing fast, need structure": 5
    }
    score = sop_map[data.sops_doc] + team_map[data.team_size] + pain_map[data.pain_point]
    max_score = 5 + 5 + 5  # 15
    return round((score / max_score) * 25)

@app.post("/generate-report")
async def generate_report(input: ScorecardInput):
    financial_score = score_financial_health(input)
    growth_score = score_growth_readiness(input)
    digital_score = score_digital_maturity(input)
    operations_score = score_operational_efficiency(input)

    total_score = financial_score + growth_score + digital_score + operations_score

    if total_score >= 90:
        label = "Built for Scale"
    elif total_score >= 70:
        label = "Growth Ready"
    elif total_score >= 50:
        label = "Developing"
    else:
        label = "Early Stage"

    # New prompt for growth advisory
    prompt = f"""
    Write a growth advisory for a {input.industry} business with:
    Financial: {financial_score}/25, Growth: {growth_score}/25, Digital: {digital_score}/25, Operations: {operations_score}/25
    Use two smart paragraphs and include 2 practical action steps.
    Format the response with:
    - **Strategic Insights**: [paragraph 1 with 2-3 bullet points]
    - **Action Steps**: [paragraph 2 with 2 bullet points for action steps]
    """

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",  # or "gpt-4" if available
            messages=[
                {"role": "system", "content": "You are a business growth advisor."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.7
        )
        advisory = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        # Fallback to hardcoded advisory in case of API failure
        advisory = f"""
        - **Strategic Insights**: This scorecard reveals a balanced profile with notable strengths in operations and digital, offering a solid base for expansion in the {input.industry} sector.
          - Leveraging these strengths can drive a competitive advantage.
          - Addressing weaker areas, such as financial and growth metrics, will unlock further potential.
        - **Action Steps**:
          - Implement a real-time financial tracking dashboard to monitor and optimize profit margins, boosting the financial score.
          - Deploy a CRM system to improve customer retention and track acquisition costs, enhancing growth readiness.
        """

    return {
        "total_score": total_score,
        "label": label,
        "breakdown": {
            "financial": financial_score,
            "growth": growth_score,
            "digital": digital_score,
            "operations": operations_score,
        },
        "advisory": advisory,
        "industry": input.industry,
        "generated_at": datetime.datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # Default to 8000 if PORT not set
    uvicorn.run(app, host="0.0.0.0", port=port)