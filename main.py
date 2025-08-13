from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
from supabase import create_client
import datetime
import os

app = FastAPI()

# Initialize OpenAI and Supabase clients
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

class AssessmentInput(BaseModel):
    revenue: float
    profit_margin_known: bool
    monthly_burn: float
    cac_tracked: bool
    retention_rate: float
    digital_campaigns: int
    analytics_tools: bool
    crm_used: bool
    data_mgmt: bool
    sops_doc: bool
    team_size: int
    pain_point: str
    industry: str

@app.post("/generate-report")
def generate_report(input: AssessmentInput):
    # === Score calculation logic ===
    financial_score = 20 if input.profit_margin_known else 10
    growth_score = input.retention_rate / 5  # Example calc
    digital_score = 20 if input.analytics_tools else 10
    operations_score = 20 if input.sops_doc else 10
    total_score = financial_score + growth_score + digital_score + operations_score

    label = (
        "High Potential" if total_score >= 70 else
        "Moderate Potential" if total_score >= 50 else
        "Needs Improvement"
    )

    # === Advisory Generation with GPT-5 ===
    try:
        gpt_prompt = (
            f"Generate a short business advisory for a company in the {input.industry} industry "
            f"based on these scores:\n"
            f"Financial: {financial_score}\nGrowth: {growth_score}\n"
            f"Digital: {digital_score}\nOperations: {operations_score}\n"
            f"Total Score: {total_score} ({label})\n"
            "Keep it under 120 words."
        )

        completion = client.responses.create(
            model="gpt-5",
            input=gpt_prompt,
            max_completion_tokens=300
        )

        advisory = completion.output_text.strip()
    except Exception as e:
        advisory = ""
        print(f"Error generating advisory: {e}")

    # Fallback if advisory is blank
    if not advisory:
        advisory = "No advisory could be generated for this assessment. Please review the inputs."

    # === Prepare scores for DB ===
    scores = {
        "financial": financial_score,
        "growth": growth_score,
        "digital": digital_score,
        "operations": operations_score
    }

    # === Save to Supabase ===
    try:
        supabase.table("basic_assessments").insert({
            "revenue": input.revenue,
            "profit_margin_known": input.profit_margin_known,
            "monthly_burn": input.monthly_burn,
            "cac_tracked": input.cac_tracked,
            "retention_rate": input.retention_rate,
            "digital_campaigns": input.digital_campaigns,
            "analytics_tools": input.analytics_tools,
            "crm_used": input.crm_used,
            "data_mgmt": input.data_mgmt,
            "sops_doc": input.sops_doc,
            "team_size": input.team_size,
            "pain_point": input.pain_point,
            "industry": input.industry,
            "scores": scores,
            "total_score": total_score,
            "advisory": advisory,
            "generated_at": datetime.datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving to Supabase: {str(e)}")

    # === Return to frontend ===
    return {
        "total_score": total_score,
        "label": label,
        "breakdown": scores,
        "advisory": advisory,
        "industry": input.industry,
        "generated_at": datetime.datetime.utcnow().isoformat()
    }
