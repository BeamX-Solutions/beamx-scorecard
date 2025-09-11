from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Literal
import datetime
import os
from openai import OpenAI
from supabase import create_client, Client
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Business Scorecard API", version="2.0.0")

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

# Set up OpenAI client with proper error handling
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")

try:
    client = OpenAI(api_key=openai_api_key)
    logger.info("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    raise ValueError(f"Failed to initialize OpenAI client: {e}")

# Initialize Supabase client with validation
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

# Enhanced input model with validation
class ScorecardInput(BaseModel):
    revenue: Literal[
        "Under $10K", 
        "$10K–$50K", 
        "$50K–$250K", 
        "$250K–$1M", 
        "Over $1M"
    ] = Field(..., description="Monthly revenue range")
    
    profit_margin_known: Literal["Yes", "No"] = Field(
        ..., description="Whether profit margins are tracked"
    )
    
    monthly_burn: Literal[
        "Unknown", 
        "≤$1K", 
        "$1K–$5K", 
        "$5K–$20K", 
        "$20K+"
    ] = Field(..., description="Monthly burn rate")
    
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
        "0 (solo)", 
        "1–3", 
        "4–10", 
        "11–50", 
        "50+"
    ] = Field(..., description="Team size")
    
    pain_point: Literal[
        "Not growing", 
        "Systems are chaotic", 
        "Don't know what to optimize", 
        "Need funding", 
        "Growing fast, need structure"
    ] = Field(..., description="Primary business pain point")
    
    industry: str = Field(..., min_length=1, max_length=100, description="Industry sector")

# --- Enhanced Scoring Functions ---
def score_financial_health(data: ScorecardInput) -> int:
    """Calculate financial health score (0-25 points)"""
    revenue_map = {
        "Under $10K": 1, 
        "$10K–$50K": 2, 
        "$50K–$250K": 3, 
        "$250K–$1M": 4, 
        "Over $1M": 5
    }
    burn_map = {
        "Unknown": 1, 
        "≤$1K": 2, 
        "$1K–$5K": 3, 
        "$5K–$20K": 4, 
        "$20K+": 5
    }
    
    revenue_score = revenue_map[data.revenue]
    profit_score = 1 if data.profit_margin_known == "Yes" else 0
    burn_score = burn_map[data.monthly_burn]
    
    total_score = revenue_score + profit_score + burn_score
    max_score = 5 + 1 + 5  # 11
    
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
    max_score = 1 + 5 + 5  # 11
    
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
    max_score = 5 + 1 + 5  # 11
    
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
        "0 (solo)": 1, 
        "1–3": 2, 
        "4–10": 3, 
        "11–50": 4, 
        "50+": 5
    }
    pain_map = {
        "Not growing": 1, 
        "Systems are chaotic": 2, 
        "Don't know what to optimize": 3,
        "Need funding": 4, 
        "Growing fast, need structure": 5
    }
    
    sop_score = sop_map[data.sops_doc]
    team_score = team_map[data.team_size]
    pain_score = pain_map[data.pain_point]
    
    total_score = sop_score + team_score + pain_score
    max_score = 5 + 5 + 5  # 15
    
    normalized_score = round((total_score / max_score) * 25)
    logger.info(f"Operations score: {normalized_score}/25 (raw: {total_score}/{max_score})")
    return normalized_score

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
    
    Provide your response in this exact format:
    **Strategic Insights:**
    • [Insight based on strongest and weakest areas]
    • [Industry-specific insight]
    • [Growth opportunity insight]
    
    **Action Steps:**
    • [Immediate actionable step addressing lowest score]
    • [Strategic step for next 90 days]
    
    Keep insights concise but actionable. Focus on the specific scores and industry context provided. Use bullet points instead of dashes for all lists and avoid em dashes throughout the response.
    """
    
    try:
        logger.info("Calling GPT-5 API for advisory generation")
        
        response = client.chat.completions.create(
            model="gpt-5",  # Using GPT-5
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
            max_completion_tokens=400,  # Updated parameter name for GPT-5
            verbosity="medium",         # GPT-5 specific parameter
            reasoning_effort="minimal"  # GPT-5 specific parameter for faster response
        )
        
        advisory = response.choices[0].message.content.strip()
        logger.info("GPT-5 advisory generated successfully")
        return advisory
        
    except Exception as e:
        logger.error(f"Error calling GPT-5 API: {e}")
        
        # Enhanced fallback advisory based on actual scores
        strongest_area = max(scores, key=scores.get)
        weakest_area = min(scores, key=scores.get)
        
        fallback_advisory = f"""
**Strategic Insights:**
- Your {strongest_area} capabilities (score: {scores[strongest_area]}/25) provide a solid foundation for growth in the {input_data.industry} sector, but {weakest_area} (score: {scores[weakest_area]}/25) needs immediate attention.
- The current pain point of "{input_data.pain_point}" directly correlates with your scoring patterns and represents your primary growth bottleneck.
- With {input_data.team_size} team members and {input_data.revenue} revenue, you're positioned for targeted improvements that can yield significant returns.

**Action Steps:**
- Address your {weakest_area} gap by implementing systematic tracking and measurement tools to improve this core business function.
- Leverage your strength in {strongest_area} to create a 90-day improvement plan that builds momentum while fixing foundational issues.
        """.strip()
        
        return fallback_advisory

@app.post("/generate-report")
async def generate_report(input_data: ScorecardInput):
    """Generate comprehensive business scorecard report"""
    
    logger.info(f"Generating report for {input_data.industry} business")
    
    try:
        # Calculate all scores
        financial_score = score_financial_health(input_data)
        growth_score = score_growth_readiness(input_data)
        digital_score = score_digital_maturity(input_data)
        operations_score = score_operational_efficiency(input_data)
        
        total_score = financial_score + growth_score + digital_score + operations_score
        
        # Determine business maturity label
        if total_score >= 90:
            label = "Built for Scale"
        elif total_score >= 70:
            label = "Growth Ready"
        elif total_score >= 50:
            label = "Developing"
        else:
            label = "Early Stage"
        
        logger.info(f"Total score: {total_score}/100, Label: {label}")
        
        # Prepare scores dictionary
        scores = {
            "financial": financial_score,
            "growth": growth_score,
            "digital": digital_score,
            "operations": operations_score
        }
        
        # Generate AI advisory using GPT-5
        advisory = await generate_gpt5_advisory(input_data, scores)
        
        # Prepare timestamp
        timestamp = datetime.datetime.utcnow().isoformat()
        
        # Save to Supabase with enhanced error handling
        try:
            logger.info("Saving assessment to Supabase")
            
            supabase_data = {
                "revenue": input_data.revenue,
                "profit_margin_known": input_data.profit_margin_known,
                "monthly_burn": input_data.monthly_burn,
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
        
        # Return comprehensive response
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
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error in generate_report: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while generating the report: {str(e)}"
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "model": "gpt-5",
        "version": "2.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
