from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict
import datetime

app = FastAPI()

# CORS configuration
origins = [
    "https://beamxsolutions.netlify.app",  # frontend on Netlify
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.post("/generate-report")
async def generate_report(input: ScorecardInput):
    # Score logic (same as previous — simplified version)
    scoring_map = {
        "revenue": {"Under $10K": 1, "$10K–$50K": 2, "$50K–$250K": 3, "$250K–$1M": 4, "Over $1M": 5},
        "profit_margin_known": {"No": 0, "Yes": 1},
        "monthly_burn": {"Unknown": 1, "≤$1K": 2, "$1K–$5K": 3, "$5K–$20K": 4, "$20K+": 5},
        "cac_tracked": {"No": 0, "Yes": 1},
        "retention_rate": {"<10%": 1, "10–25%": 2, "25–50%": 3, "50–75%": 4, "75%+": 5},
        "digital_campaigns": {"No": 1, "Sometimes": 3, "Consistently": 5},
        "analytics_tools": {
            "No": 1,
            "Basic tools (Excel, etc.)": 3,
            "Advanced or custom dashboards": 5
        },
        "crm_used": {"No": 0, "Yes": 1},
        "data_mgmt": {
            "Scattered or manual": 1,
            "Somewhat structured": 3,
            "Centralized and automated": 5
        },
        "sops_doc": {"No": 1, "Somewhat": 3, "Fully documented": 5},
        "team_size": {"0 (solo)": 1, "1–3": 2, "4–10": 3, "11–50": 4, "50+": 5},
    }

    def score_field(field: str) -> int:
        return scoring_map.get(field, {}).get(getattr(input, field), 0)

    financial_score = (
        score_field("revenue") +
        score_field("profit_margin_known") +
        score_field("monthly_burn")
    )
    growth_score = (
        score_field("cac_tracked") +
        score_field("retention_rate") +
        score_field("digital_campaigns")
    )
    digital_score = (
        score_field("analytics_tools") +
        score_field("crm_used") +
        score_field("data_mgmt")
    )
    operations_score = (
        score_field("sops_doc") +
        score_field("team_size")
    )

    # Normalize scores
    total_score = financial_score + growth_score + digital_score + operations_score
    total_out_of = 25 + 25 + 25 + 25
    final_score = round((total_score / total_out_of) * 100)

    if final_score >= 90:
        label = "Built for Scale"
    elif final_score >= 70:
        label = "Growth Ready"
    elif final_score >= 50:
        label = "Developing"
    else:
        label = "Early Stage"

    insights = (
        f"Your E-commerce business is performing remarkably well in the areas of "
        f"growth, digital and operations. However, there is room for improvement in the financial aspect. "
        f"To elevate your financial score, consider real-time financial tracking and optimizing pricing strategy. "
        f"Efficient supply chain management can also reduce costs and improve delivery."
    )

    html_report = f"""
    <h3>Customized Recommendations</h3>
    <ul>
        <li><strong>Financial:</strong> Track profit margins and manage burn rate effectively.</li>
        <li><strong>Growth:</strong> Focus on improving customer retention and CAC tracking.</li>
        <li><strong>Digital:</strong> Invest in CRM and analytics platforms for better insights.</li>
        <li><strong>Operations:</strong> Continue developing SOPs and expanding team structure.</li>
    </ul>
    """

    return {
        "total_score": final_score,
        "label": label,
        "breakdown": {
            "financial": financial_score,
            "growth": growth_score,
            "digital": digital_score,
            "operations": operations_score,
        },
        "insight": insights,
        "html_report": html_report,
        "industry": input.industry,
        "generated_at": datetime.datetime.utcnow().isoformat()
    }
