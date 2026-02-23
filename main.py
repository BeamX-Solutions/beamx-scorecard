from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Dict, List, Literal
from dataclasses import dataclass
import datetime
import os
import base64
import io
import re
import logging
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration
from supabase import create_client, Client
from openai import OpenAI
import resend

# ─────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Beacon SME Assessment API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://beamxsolutions.com", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
resend_api_key = os.getenv("RESEND_API_KEY")
from_email = os.getenv("FROM_EMAIL", "noreply@beamxsolutions.com")
if resend_api_key:
    resend.api_key = resend_api_key


# ─────────────────────────────────────────────
# INPUT SCHEMA
# ─────────────────────────────────────────────

class BeaconSMEInput(BaseModel):
    fullName: str = Field(min_length=1, max_length=100)
    email: EmailStr
    businessName: str = Field(min_length=1, max_length=150)
    industry: Literal[
        "Retail/Trade", "Food & Beverage", "Professional Services",
        "Beauty & Personal Care", "Logistics & Transportation",
        "Manufacturing/Production", "Hospitality", "Construction/Trades",
        "Healthcare Services", "Education/Training", "Agriculture", "Other"
    ]
    yearsInBusiness: Literal[
        "Less than 1 year", "1-3 years", "3-5 years", "5-10 years", "10+ years"
    ]
    cashFlow: Literal[
        "Consistent surplus", "Breaking even",
        "Unpredictable (some surplus, some deficit)",
        "Burning cash consistently", "Don't know"
    ]
    profitMargin: Literal[
        "30%+", "20-30%", "10-20%", "5-10%",
        "Less than 5% or negative", "Don't know"
    ]
    cashRunway: Literal[
        "6+ months", "3-6 months", "1-3 months",
        "Less than 1 month", "Would close immediately"
    ]
    paymentSpeed: Literal[
        "Same day (cash/instant)", "1-7 days", "8-30 days", "31-60 days", "60+ days"
    ]
    repeatCustomerRate: Literal[
        "70%+ repeat customers", "50-70% repeat", "30-50% repeat",
        "10-30% repeat", "Less than 10% repeat"
    ]
    acquisitionChannel: Literal[
        "Referrals/word-of-mouth", "Walk-ins/location visibility",
        "Organic social media", "Repeat business relationships",
        "Paid advertising", "Cold outreach", "Don't know"
    ]
    pricingPower: Literal[
        "Tested increases successfully", "Most customers would stay",
        "Some would leave but still profitable", "Would lose most customers", "Don't know"
    ]
    founderDependency: Literal[
        "Runs 2+ weeks without me", "Can step away 1 week",
        "2-3 days max", "Can't miss even 1 day", "Must be there daily"
    ]
    processDocumentation: Literal[
        "Comprehensive written processes", "Some key processes documented",
        "Trained others, mostly in my head", "Everything in my head only", "No consistent processes"
    ]
    inventoryTracking: Literal[
        "Digital real-time system", "Regular manual/spreadsheet",
        "Weekly physical count", "Only when running low",
        "Don't track", "Not applicable (service business)"
    ]
    expenseAwareness: Literal[
        "Know exact amounts and percentages", "Know roughly",
        "General idea", "Would have to look up", "No idea"
    ]
    profitPerProduct: Literal[
        "Know margins on each offering", "Good sense of what's profitable",
        "Know revenue only, not profit", "Haven't analyzed", "All seem about the same"
    ]
    pricingStrategy: Literal[
        "Cost + margin + market research", "Match competitors",
        "Cost + markup (no market analysis)", "What feels right", "No strategy"
    ]
    businessTrajectory: Literal[
        "Growing 20%+", "Growing 5-20%", "Stable (±5%)",
        "Declining 5-20%", "Declining 20%+", "Less than 1 year old"
    ]
    revenueDiversification: Literal[
        "4+ streams/customer types", "2-3 streams", "Primary + side income",
        "Single product/customer type", "Dependent on 1-2 major customers"
    ]
    digitalPayments: Literal[
        "80%+ digital", "50-80% digital", "20-50% digital", "Less than 20% digital"
    ]
    formalRegistration: Literal[
        "Fully registered and tax compliant", "Registered, behind on taxes",
        "In process of registering", "Not registered"
    ]
    infrastructure: Literal[
        "Consistent power/internet/supply", "Mostly reliable with backups",
        "Frequent disruptions", "Major challenges daily"
    ]
    bankingRelationship: Literal[
        "Strong, accessed loans/credit", "Accounts but no credit",
        "Minimal interaction", "No bank relationship"
    ]
    primaryPainPoint: Literal[
        "Getting more customers/sales", "Managing cash flow/getting paid",
        "Hiring or managing staff", "Keeping costs under control",
        "Too busy/overwhelmed", "Inconsistent quality/delivery",
        "Don't know where to focus", "Competition/market changes",
        "Actually doing well, want to optimize"
    ]


# ─────────────────────────────────────────────
# SCORING MAPS
# ─────────────────────────────────────────────

CASH_FLOW_MAP = {
    "Consistent surplus": 5, "Breaking even": 3,
    "Unpredictable (some surplus, some deficit)": 2,
    "Burning cash consistently": 0, "Don't know": 0,
}
PROFIT_MARGIN_MAP = {
    "30%+": 5, "20-30%": 4, "10-20%": 3,
    "5-10%": 2, "Less than 5% or negative": 1, "Don't know": 0,
}
CASH_RUNWAY_MAP = {
    "6+ months": 5, "3-6 months": 4, "1-3 months": 2,
    "Less than 1 month": 1, "Would close immediately": 0,
}
PAYMENT_SPEED_MAP = {
    "Same day (cash/instant)": 5, "1-7 days": 4,
    "8-30 days": 3, "31-60 days": 1, "60+ days": 0,
}
REPEAT_RATE_MAP = {
    "70%+ repeat customers": 5, "50-70% repeat": 4,
    "30-50% repeat": 3, "10-30% repeat": 2, "Less than 10% repeat": 0,
}
ACQUISITION_MAP = {
    "Referrals/word-of-mouth": 5, "Repeat business relationships": 5,
    "Walk-ins/location visibility": 3, "Organic social media": 3,
    "Paid advertising": 2, "Cold outreach": 1, "Don't know": 0,
}
PRICING_POWER_MAP = {
    "Tested increases successfully": 5, "Most customers would stay": 4,
    "Some would leave but still profitable": 3,
    "Would lose most customers": 1, "Don't know": 1,
}
FOUNDER_DEPENDENCY_MAP = {
    "Runs 2+ weeks without me": 5, "Can step away 1 week": 4,
    "2-3 days max": 3, "Can't miss even 1 day": 1, "Must be there daily": 0,
}
PROCESS_DOC_MAP = {
    "Comprehensive written processes": 5, "Some key processes documented": 4,
    "Trained others, mostly in my head": 2,
    "Everything in my head only": 1, "No consistent processes": 0,
}
INVENTORY_MAP = {
    "Digital real-time system": 5, "Regular manual/spreadsheet": 4,
    "Weekly physical count": 3, "Only when running low": 1,
    "Don't track": 0, "Not applicable (service business)": 4,
}
EXPENSE_AWARENESS_MAP = {
    "Know exact amounts and percentages": 5, "Know roughly": 4,
    "General idea": 3, "Would have to look up": 1, "No idea": 0,
}
PROFIT_PER_PRODUCT_MAP = {
    "Know margins on each offering": 5, "Good sense of what's profitable": 4,
    "Know revenue only, not profit": 2,
    "Haven't analyzed": 1, "All seem about the same": 1,
}
PRICING_STRATEGY_MAP = {
    "Cost + margin + market research": 5, "Match competitors": 3,
    "Cost + markup (no market analysis)": 2,
    "What feels right": 1, "No strategy": 0,
}
TRAJECTORY_MAP = {
    "Growing 20%+": 5, "Growing 5-20%": 4, "Stable (±5%)": 3,
    "Declining 5-20%": 1, "Declining 20%+": 0, "Less than 1 year old": 2,
}
DIVERSIFICATION_MAP = {
    "4+ streams/customer types": 5, "2-3 streams": 4,
    "Primary + side income": 3, "Single product/customer type": 2,
    "Dependent on 1-2 major customers": 0,
}
DIGITAL_PAYMENTS_MAP = {
    "80%+ digital": 5, "50-80% digital": 4,
    "20-50% digital": 2, "Less than 20% digital": 1,
}
FORMALIZATION_MAP = {
    "Fully registered and tax compliant": 5, "Registered, behind on taxes": 3,
    "In process of registering": 2, "Not registered": 0,
}
INFRASTRUCTURE_MAP = {
    "Consistent power/internet/supply": 5, "Mostly reliable with backups": 4,
    "Frequent disruptions": 2, "Major challenges daily": 0,
}
BANKING_MAP = {
    "Strong, accessed loans/credit": 5, "Accounts but no credit": 3,
    "Minimal interaction": 1, "No bank relationship": 0,
}


# ─────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────

@dataclass
class CategoryScore:
    name: str
    score: float
    max_score: float
    percentage: float
    grade: str
    insights: List[str]

@dataclass
class BeaconScore:
    total_score: float
    readiness_level: str
    financial_health: CategoryScore
    customer_strength: CategoryScore
    operational_maturity: CategoryScore
    financial_intelligence: CategoryScore
    growth_resilience: CategoryScore
    primary_pain_point: str
    industry: str
    years_in_business: str
    critical_flags: List[str]
    opportunity_flags: List[str]


# ─────────────────────────────────────────────
# INSIGHT GENERATORS
# ─────────────────────────────────────────────

def _generate_fh_insights(data: BeaconSMEInput) -> List[str]:
    insights = []
    if data.cashFlow == "Consistent surplus":
        insights.append("Strong cash flow discipline - foundation for growth")
    elif data.cashFlow == "Burning cash consistently":
        insights.append("Burning cash monthly - immediate action required")
    elif data.cashFlow == "Don't know":
        insights.append("No cash flow tracking - serious financial risk")
    if data.profitMargin in ["30%+", "20-30%"]:
        insights.append("Healthy profit margins - room to invest and weather storms")
    elif data.profitMargin in ["5-10%", "Less than 5% or negative"]:
        insights.append("Thin margins - vulnerable to any cost increases")
    elif data.profitMargin == "Don't know":
        insights.append("Unknown profitability - you cannot make informed decisions")
    if data.cashRunway in ["Less than 1 month", "Would close immediately"]:
        insights.append("CRITICAL: Less than 30 days cash runway")
    elif data.cashRunway == "6+ months":
        insights.append("Strong cash reserves - positioned for opportunities")
    if data.paymentSpeed in ["31-60 days", "60+ days"]:
        insights.append("Slow payment collection is straining cash flow")
    elif data.paymentSpeed == "Same day (cash/instant)":
        insights.append("Fast payment collection - excellent cash velocity")
    return insights

def _generate_cs_insights(data: BeaconSMEInput) -> List[str]:
    insights = []
    if data.repeatCustomerRate == "70%+ repeat customers":
        insights.append("Exceptional customer loyalty - strong retention foundation")
    elif data.repeatCustomerRate == "Less than 10% repeat":
        insights.append("Low repeat business - acquisition treadmill is expensive")
    if data.acquisitionChannel in ["Referrals/word-of-mouth", "Repeat business relationships"]:
        insights.append("Organic acquisition - sustainable and low-cost growth engine")
    elif data.acquisitionChannel == "Paid advertising":
        insights.append("Paid-dependent growth - vulnerable if ad budget must be cut")
    elif data.acquisitionChannel == "Don't know":
        insights.append("Unknown acquisition source - you cannot optimize what you don't track")
    if data.pricingPower == "Tested increases successfully":
        insights.append("Proven pricing power - differentiated from competition")
    elif data.pricingPower == "Would lose most customers":
        insights.append("Commoditized offering - competing on price alone")
    return insights

def _generate_om_insights(data: BeaconSMEInput) -> List[str]:
    insights = []
    if data.founderDependency == "Must be there daily":
        insights.append("Business cannot run without you - burnout risk and zero scale potential")
    elif data.founderDependency == "Runs 2+ weeks without me":
        insights.append("Business independence achieved - scalable operations")
    if data.processDocumentation == "Comprehensive written processes":
        insights.append("Strong documentation - ready to train, delegate, and scale")
    elif data.processDocumentation in ["Everything in my head only", "No consistent processes"]:
        insights.append("Tribal knowledge only - vulnerable to any key person leaving")
    if data.inventoryTracking == "Digital real-time system":
        insights.append("Real-time inventory visibility - optimal stock management")
    elif data.inventoryTracking == "Don't track":
        insights.append("No inventory tracking - likely experiencing costly stockouts or overstock")
    return insights

def _generate_fi_insights(data: BeaconSMEInput) -> List[str]:
    insights = []
    if data.expenseAwareness == "Know exact amounts and percentages":
        insights.append("Strong cost control discipline - ready to optimize")
    elif data.expenseAwareness in ["Would have to look up", "No idea"]:
        insights.append("Weak expense visibility - almost certainly leaving money on the table")
    if data.profitPerProduct == "Know margins on each offering":
        insights.append("Margin awareness - you can focus effort on your most profitable offerings")
    elif data.profitPerProduct in ["Haven't analyzed", "All seem about the same"]:
        insights.append("No margin analysis - you may be subsidizing loss-makers with your winners")
    if data.pricingStrategy == "Cost + margin + market research":
        insights.append("Strategic pricing approach - maximizing value capture")
    elif data.pricingStrategy in ["What feels right", "No strategy"]:
        insights.append("Arbitrary pricing - you are likely undercharging or mispricing")
    return insights

def _generate_gr_insights(data: BeaconSMEInput) -> List[str]:
    insights = []
    if data.businessTrajectory in ["Growing 20%+", "Growing 5-20%"]:
        insights.append("Positive growth trajectory - strong market validation")
    elif data.businessTrajectory in ["Declining 5-20%", "Declining 20%+"]:
        insights.append("Declining revenue - urgent strategic review needed")
    if data.revenueDiversification == "Dependent on 1-2 major customers":
        insights.append("Customer concentration risk - one lost client could cripple the business")
    elif data.revenueDiversification == "4+ streams/customer types":
        insights.append("Well-diversified revenue - resilient to market shifts")
    if data.digitalPayments in ["80%+ digital", "50-80% digital"]:
        insights.append("Strong digital payment adoption - good transaction visibility")
    elif data.digitalPayments == "Less than 20% digital":
        insights.append("Cash-heavy operations - limited data visibility")
    if data.formalRegistration == "Fully registered and tax compliant":
        insights.append("Fully formalized - eligible for credit, partnerships, and major contracts")
    elif data.formalRegistration == "Not registered":
        insights.append("Informal operations - locked out of growth capital and corporate clients")
    if data.infrastructure == "Major challenges daily":
        insights.append("Daily infrastructure disruptions are hurting operational efficiency")
    if data.bankingRelationship == "Strong, accessed loans/credit":
        insights.append("Banking access established - growth capital is available to you")
    return insights


# ─────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────

def calculate_beacon_score(data: BeaconSMEInput) -> BeaconScore:
    def get_grade(pct: float) -> str:
        if pct >= 90: return "A"
        elif pct >= 80: return "B+"
        elif pct >= 70: return "B"
        elif pct >= 60: return "C+"
        elif pct >= 50: return "C"
        else: return "D"

    fh_raw = (CASH_FLOW_MAP[data.cashFlow] + PROFIT_MARGIN_MAP[data.profitMargin] +
              CASH_RUNWAY_MAP[data.cashRunway] + PAYMENT_SPEED_MAP[data.paymentSpeed])
    fh_score = (fh_raw / 20) * 20

    cs_raw = (REPEAT_RATE_MAP[data.repeatCustomerRate] + ACQUISITION_MAP[data.acquisitionChannel] +
              PRICING_POWER_MAP[data.pricingPower])
    cs_score = (cs_raw / 15) * 20

    om_raw = (FOUNDER_DEPENDENCY_MAP[data.founderDependency] + PROCESS_DOC_MAP[data.processDocumentation] +
              INVENTORY_MAP[data.inventoryTracking])
    om_score = (om_raw / 15) * 20

    fi_raw = (EXPENSE_AWARENESS_MAP[data.expenseAwareness] + PROFIT_PER_PRODUCT_MAP[data.profitPerProduct] +
              PRICING_STRATEGY_MAP[data.pricingStrategy])
    fi_score = (fi_raw / 15) * 20

    gr_base = TRAJECTORY_MAP[data.businessTrajectory] + DIVERSIFICATION_MAP[data.revenueDiversification]
    gr_base_score = (gr_base / 10) * 12
    context_raw = (
        (DIGITAL_PAYMENTS_MAP[data.digitalPayments] / 5 * 2) +
        (FORMALIZATION_MAP[data.formalRegistration] / 5 * 3) +
        (INFRASTRUCTURE_MAP[data.infrastructure] / 5 * 2) +
        (BANKING_MAP[data.bankingRelationship] / 5 * 1)
    )
    gr_score = gr_base_score + context_raw
    total = fh_score + cs_score + om_score + fi_score + gr_score

    if total >= 85:   level = "🏆 Scale-Ready"
    elif total >= 70: level = "💪 Stable Foundation"
    elif total >= 50: level = "🔨 Building Blocks"
    elif total >= 30: level = "⚠️ Survival Mode"
    else:             level = "🚨 Red Alert"

    critical_flags = []
    if data.cashFlow in ["Burning cash consistently", "Don't know"]:
        critical_flags.append("CASH_CRISIS")
    if data.cashRunway in ["Less than 1 month", "Would close immediately"]:
        critical_flags.append("RUNWAY_CRITICAL")
    if data.profitMargin in ["Less than 5% or negative", "Don't know"]:
        critical_flags.append("NO_PROFIT_VISIBILITY")
    if data.founderDependency == "Must be there daily":
        critical_flags.append("FOUNDER_BURNOUT_RISK")
    if data.formalRegistration == "Not registered":
        critical_flags.append("INFORMAL_OPERATIONS")
    if data.repeatCustomerRate == "Less than 10% repeat":
        critical_flags.append("NO_CUSTOMER_LOYALTY")

    opportunity_flags = []
    if data.pricingPower in ["Tested increases successfully", "Most customers would stay"]:
        opportunity_flags.append("PRICING_POWER")
    if data.repeatCustomerRate == "70%+ repeat customers":
        opportunity_flags.append("STRONG_RETENTION")
    if data.acquisitionChannel in ["Referrals/word-of-mouth", "Repeat business relationships"]:
        opportunity_flags.append("ORGANIC_GROWTH")
    if data.processDocumentation == "Comprehensive written processes":
        opportunity_flags.append("SYSTEMS_READY")
    if fh_score >= 16:
        opportunity_flags.append("FINANCIAL_DISCIPLINE")

    def make_cat(name, score, max_s, insights_fn):
        pct = round((score / max_s) * 100, 1)
        return CategoryScore(name=name, score=round(score, 1), max_score=max_s,
                             percentage=pct, grade=get_grade(pct), insights=insights_fn(data))

    return BeaconScore(
        total_score=round(total, 1),
        readiness_level=level,
        financial_health=make_cat("Financial Health", fh_score, 20, _generate_fh_insights),
        customer_strength=make_cat("Customer Strength", cs_score, 20, _generate_cs_insights),
        operational_maturity=make_cat("Operational Maturity", om_score, 20, _generate_om_insights),
        financial_intelligence=make_cat("Financial Intelligence", fi_score, 20, _generate_fi_insights),
        growth_resilience=make_cat("Growth & Resilience", gr_score, 20, _generate_gr_insights),
        primary_pain_point=data.primaryPainPoint,
        industry=data.industry,
        years_in_business=data.yearsInBusiness,
        critical_flags=critical_flags,
        opportunity_flags=opportunity_flags,
    )


# ─────────────────────────────────────────────
# STEP 1: RULE-BASED ADVISORY BUILDER
# ─────────────────────────────────────────────

def _generate_executive_summary(score: BeaconScore) -> str:
    summaries = {
        "Scale-Ready": f"""## Executive Summary\n\n**Your Business:** {score.readiness_level}\n\nCongratulations! Your business demonstrates strong fundamentals across all key dimensions. You've built a sustainable operation with {score.financial_health.grade}-grade financial health, {score.customer_strength.grade}-grade customer relationships, and the operational systems to support growth.\n\n**What this means:** You're ready for strategic expansion—whether that's new locations, product lines, strategic partnerships, or accessing growth capital. Your focus should shift from survival to optimization and scale.\n\n**Overall Score:** {score.total_score}/100""",
        "Stable Foundation": f"""## Executive Summary\n\n**Your Business:** {score.readiness_level}\n\nYou've built a solid, working business with stable operations and clear revenue. Your {score.financial_health.percentage}% financial health score and {score.customer_strength.percentage}% customer strength indicate a sustainable foundation. However, there are specific areas that, if strengthened, will unlock significant growth potential.\n\n**What this means:** You're not in crisis, but you're also not yet optimized for scale. Strategic improvements in 2-3 key areas could move you from "stable" to "thriving" within 6-12 months.\n\n**Overall Score:** {score.total_score}/100""",
        "Building Blocks": f"""## Executive Summary\n\n**Your Business:** {score.readiness_level}\n\nYour business is operational and generating revenue, but showing fragility in critical areas. With a {score.total_score}/100 overall score, you're functioning but not yet positioned for sustainable growth.\n\n**What this means:** You need focused attention on shoring up weaknesses before pursuing aggressive growth. Think "strengthen the foundation" before "build the second floor."\n\n**Overall Score:** {score.total_score}/100""",
        "Survival Mode": f"""## Executive Summary\n\n**Your Business:** {score.readiness_level}\n\nYour assessment reveals critical gaps that are likely causing significant daily stress. With a {score.total_score}/100 score, your business is functioning but facing serious sustainability challenges.\n\n**What this means:** You're in triage mode. This is not about growth right now—it's about stabilizing operations, fixing cash flow, and creating breathing room.\n\n**Overall Score:** {score.total_score}/100""",
        "Red Alert": f"""## Executive Summary\n\n**Your Business:** {score.readiness_level}\n\nThis assessment reveals urgent challenges that require immediate attention. With a {score.total_score}/100 score, your business is facing existential risks. However, honest diagnosis is the first step toward recovery.\n\n**What this means:** You need rapid, decisive action in the next 30-60 days. Every recommendation below is prioritized for immediate cash preservation and triage.\n\n**Overall Score:** {score.total_score}/100""",
    }
    for key in summaries:
        if key in score.readiness_level:
            return summaries[key]
    return summaries["Building Blocks"]


def _generate_critical_priorities(score: BeaconScore) -> str:
    section = "## 🚨 Critical Priorities (Next 30 Days)\n\n*These issues require immediate attention and could threaten business viability if left unaddressed.*\n\n"
    priorities = []
    flag_content = {
        "CASH_CRISIS": "**CASH FLOW EMERGENCY**\n- You're burning cash or don't know your position—both are existential threats\n- **Immediate:** Create a simple daily cash tracker (cash in vs. cash out)\n- **This week:** Identify your 3 biggest cash drains and cut/defer at least one\n- **This month:** Implement weekly cash flow forecasting",
        "RUNWAY_CRITICAL": "**RUNWAY EXTENSION REQUIRED**\n- Less than 30 days of cash runway means you're one bad week from closure\n- **Immediate:** List every receivable and chase payment this week\n- **Emergency:** Negotiate payment terms with suppliers, defer non-essential expenses\n- **Revenue injection:** Flash sale, prepay discounts, or close pending deals faster",
        "NO_PROFIT_VISIBILITY": "**PROFIT BLINDNESS**\n- You can't manage what you don't measure—unknown margins = random outcomes\n- **This week:** Calculate gross profit on your top 3 products/services\n- **This month:** Build a simple P&L (revenue - all costs = profit)\n- **Ongoing:** Track monthly profitability, not just revenue",
        "FOUNDER_BURNOUT_RISK": "**FOUNDER DEPENDENCY CRISIS**\n- If you can't miss a day, you don't own a business—you own a job\n- **This month:** Document your daily tasks and delegate/eliminate at least 3\n- **Strategic:** Identify the ONE task only you can do, systematize everything else",
        "INFORMAL_OPERATIONS": "**FORMALIZATION GAP**\n- Operating informally locks you out of credit, partnerships, and major contracts\n- **This month:** Register your business (CAC, BN, or equivalent)\n- **Follow-up:** Get a tax ID and open a dedicated business bank account",
        "NO_CUSTOMER_LOYALTY": "**RETENTION CRISIS**\n- Less than 10% repeat rate means you're constantly refilling a leaky bucket\n- **Immediate:** Survey your last 20 customers—why did they buy? Would they return?\n- **This month:** Implement ONE retention tactic (follow-up calls, loyalty rewards, check-ins)",
    }
    for flag in score.critical_flags:
        if flag in flag_content:
            priorities.append(flag_content[flag])
    section += "\n\n".join(priorities[:3])
    if len(priorities) > 3:
        section += f"\n\n*Note: You have {len(priorities)} critical issues flagged. Top 3 shown above.*"
    return section


def _get_category_recommendation(category_name: str, category: CategoryScore, score: BeaconScore) -> str:
    recs = {
        "Financial Health": f"### Strengthen Financial Health (Current: {category.grade})\n\n**Your situation:** {category.percentage}% score indicates cash flow, profitability, or visibility gaps.\n\n**90-Day Action Plan:**\n- **Week 1-2:** Set up basic cash flow tracking (daily cash in/out)\n- **Week 3-4:** Calculate true profit margin on your top offerings\n- **Month 2:** Build a 30-day cash buffer by cutting non-essentials and accelerating collections\n- **Month 3:** Implement a weekly P&L review habit\n\n**Quick Win:** Identify and eliminate your single biggest cash leak this month.\n\n**Metric to Track:** Days of cash runway (target: 90+ days)",
        "Customer Strength": f"### Build Customer Strength (Current: {category.grade})\n\n**Your situation:** {category.percentage}% score suggests weak retention, expensive acquisition, or a commoditized offering.\n\n**90-Day Action Plan:**\n- **Week 1-2:** Contact your best 10 customers—understand why they stay and what would make them leave\n- **Week 3-4:** Implement ONE retention mechanism (loyalty program, follow-up system, VIP treatment)\n- **Month 2:** Test a 10% price increase on new customers only\n- **Month 3:** Create a referral incentive program\n\n**Quick Win:** Send a personal thank-you to your top 20 customers this week. Ask for referrals.\n\n**Metric to Track:** % repeat customer revenue (target: 50%+)",
        "Operational Maturity": f"### Systematize Operations (Current: {category.grade})\n\n**Your situation:** {category.percentage}% score indicates founder dependency and weak processes.\n\n**90-Day Action Plan:**\n- **Week 1-2:** Time-track your week—identify tasks only you can do vs. tasks anyone could do\n- **Week 3-4:** Document your top 3 repetitive processes (even bullet points work)\n- **Month 2:** Delegate or eliminate at least 5 hours/week of non-essential tasks\n- **Month 3:** Train one person to handle a key process without your involvement\n\n**Quick Win:** Record a 5-minute voice note explaining one recurring task. Use it to delegate next week.\n\n**Metric to Track:** Days business can run without you (target: 7+ days)",
        "Financial Intelligence": f"### Sharpen Financial Intelligence (Current: {category.grade})\n\n**Your situation:** {category.percentage}% score means you lack visibility into what actually drives profit.\n\n**90-Day Action Plan:**\n- **Week 1-2:** List all major expenses and their % of revenue\n- **Week 3-4:** Calculate gross margin on each product/service you offer\n- **Month 2:** Identify your highest-margin offering and push it harder\n- **Month 3:** Eliminate or fix your lowest-margin offering\n\n**Quick Win:** This week, calculate (Revenue - All Costs) ÷ Revenue = Your Profit Margin. If below 15%, you have a pricing or cost problem.\n\n**Metric to Track:** Gross profit margin by product line (target: know all margins)",
        "Growth & Resilience": f"### Build Growth & Resilience (Current: {category.grade})\n\n**Your situation:** {category.percentage}% score suggests concentration risk or a declining trajectory.\n\n**90-Day Action Plan:**\n- **Week 1-2:** Analyze revenue sources—how dependent are you on 1-2 customers or products?\n- **Week 3-4:** Identify one new customer segment or revenue stream to test\n- **Month 2:** Pilot the new offering with 5-10 customers\n- **Month 3:** Evaluate and either double down or pivot\n\n**Quick Win:** If one customer represents >25% of revenue, reach out to 10 prospects in a different segment this month.\n\n**Metric to Track:** Revenue concentration (target: no single customer >20% of revenue)",
    }
    return recs.get(category_name, "")


def _get_pain_point_recommendation(score: BeaconScore) -> str:
    pain_recs = {
        "Getting more customers/sales": f"### Tactical Growth Plan\n\n**Root cause from your scores:**\n- Customer Strength: {score.customer_strength.grade} ({score.customer_strength.percentage}%)\n- Financial Intelligence: {score.financial_intelligence.grade} ({score.financial_intelligence.percentage}%)\n\n**Recommended sequence:**\n1. **Fix retention before acquisition** — if <50% repeat rate, you're filling a leaky bucket\n2. **Leverage existing customers:** Ask top 20 for referrals, build testimonials, run a \"bring a friend\" promotion\n3. **Test low-cost channels first:** Partnerships, local community, organic social proof\n4. **Only then** consider paid acquisition\n\n*Retention is 5-10x cheaper than acquisition. Fix the foundation first.*",
        "Managing cash flow/getting paid": f"### Cash Flow Rescue Plan\n\n**Current situation:**\n- Financial Health: {score.financial_health.grade} ({score.financial_health.percentage}%)\n\n**Immediate actions (this week):**\n1. Call every customer with outstanding invoices >15 days — offer 5% discount for immediate payment\n2. Negotiate longer payment terms with your top suppliers\n3. Audit last month's expenses — cut the bottom 20%\n\n**30-60 day fixes:**\n- Require 30-50% deposits before starting any work\n- Move to weekly invoicing instead of monthly\n- Implement late payment penalties in all new contracts\n\n*Cash is oxygen. You can survive without profit temporarily — not without cash.*",
        "Hiring or managing staff": f"### Team Management Fix\n\n**Context from assessment:**\n- Operational Maturity: {score.operational_maturity.grade} ({score.operational_maturity.percentage}%)\n\n**Diagnosis:** Staff problems are almost always systems problems, not people problems.\n\n**Solution framework:**\n1. Before hiring more: Document what \"good\" looks like for each role and set clear KPIs\n2. For existing team issues: Weekly 15-min 1-on-1s — diagnose if the issue is skills (train), will (motivate), or fit (part ways)\n3. Reduce founder dependency: Train a second-in-command, batch your check-ins instead of constant monitoring\n\n*If you're working 60+ hours but staff are working 30-40, you have a delegation problem, not a staffing problem.*",
        "Keeping costs under control": f"### Cost Optimization Plan\n\n**Current situation:**\n- Financial Intelligence: {score.financial_intelligence.grade} ({score.financial_intelligence.percentage}%)\n\n**The 80/20 audit (this week):**\n1. List every expense from last month\n2. Categorize: Essential (can't operate without) / Important (would hurt to lose) / Nice-to-have (comfort, not survival)\n3. Cut 20% from the \"nice-to-have\" category immediately\n\n**Deeper fixes (30-60 days):** Renegotiate your top 3 expenses (rent, suppliers, staff structure), track cost per unit/transaction, stop doing things where cost exceeds revenue.\n\n*Cutting costs is not the goal — improving profit margin is. Sometimes spending more in the right area increases overall profit.*",
        "Too busy/overwhelmed": f"### Founder Liberation Plan\n\n**Root cause:**\n- Operational Maturity: {score.operational_maturity.grade} ({score.operational_maturity.percentage}%)\n- You're likely doing low-value tasks when you should focus on high-leverage ones\n\n**The Stop, Delegate, Systemize Framework:**\n- **Week 1 — STOP:** Tasks that don't directly generate revenue or that someone else could do 80% as well\n- **Week 2-3 — DELEGATE:** Bring in a VA or part-timer for admin, train a team member on routine customer issues\n- **Week 4+ — SYSTEMIZE:** Simple SOPs (even voice notes), batch similar tasks, set firm off-hours boundaries\n\n**Target state:** You work ON the business (strategy, key deals) — not IN it (daily operations).",
        "Inconsistent quality/delivery": f"### Quality Control System\n\n**Root cause:**\n- Operational Maturity: {score.operational_maturity.grade} ({score.operational_maturity.percentage}%)\n\n**Fix in 4 steps:**\n1. **DEFINE \"good\":** Write down what success looks like for each key process — even 10 bullet points\n2. **CREATE checklists:** Every recurring task gets a checklist; staff check off each step before marking complete\n3. **INSPECT:** Random quality checks (unannounced), review customer complaints weekly for patterns\n4. **REWARD consistency:** Tie bonuses to quality metrics, not just sales volume\n\n*Inconsistency kills trust. Trust is the foundation of repeat business.*",
        "Don't know where to focus": f"### Strategic Clarity Framework\n\n**Your assessment gives you the answer. Priority ranking (fix in this order):**\n- Financial Health: {score.financial_health.grade} ({score.financial_health.percentage}%)\n- Customer Strength: {score.customer_strength.grade} ({score.customer_strength.percentage}%)\n- Operational Maturity: {score.operational_maturity.grade} ({score.operational_maturity.percentage}%)\n- Financial Intelligence: {score.financial_intelligence.grade} ({score.financial_intelligence.percentage}%)\n- Growth & Resilience: {score.growth_resilience.grade} ({score.growth_resilience.percentage}%)\n\n**Daily decision rule:**\n- If cash flow is negative → focus ONLY on cash first\n- If cash flow is stable → work on your lowest-scoring category\n- If growing fast → fix systems before you break\n\n*Trying to fix everything at once fixes nothing. Pick ONE thing, execute for 30 days, then reassess.*",
        "Competition/market changes": f"### Competitive Response Plan\n\n**Strategic position:**\n- Customer Strength: {score.customer_strength.grade} ({score.customer_strength.percentage}%)\n\n**Reality check:** Competition is usually a symptom. The disease is commoditized offering, weak customer relationships, or competing on price alone.\n\n**3-Part Strategy:**\n1. **DIFFERENTIATE:** What can you do that competitors can't or won't? (Faster delivery, better service, expertise, guarantees)\n2. **DEEPEN loyalty:** Make it expensive — emotionally and logistically — for customers to switch\n3. **DOMINATE a niche:** Better to own 80% of a small market than 2% of a large one\n\n*If you raised prices 15% tomorrow and would lose most customers, you're commoditized. Fix that before worrying about competition.*",
        "Actually doing well, want to optimize": f"### Optimization Playbook\n\n**Current performance:** {score.total_score}/100 — {score.readiness_level}\n\n**Optimization priorities (in order):**\n1. **Margin expansion:** Push highest-margin offerings harder, eliminate lowest-margin ones, test 5-10% price increases on new customers\n2. **Customer lifetime value:** Increase purchase frequency (subscriptions, memberships), upsell/cross-sell to existing base\n3. **Operational leverage:** Document and delegate to free 10+ hours/week, reinvest that time into strategy\n4. **Strategic positioning:** Build a board of advisors, explore alliances and partnership opportunities",
    }
    return pain_recs.get(score.primary_pain_point, "")


def _get_industry_recommendation(score: BeaconScore) -> str:
    industry_insights = {
        "Retail/Trade": "### Industry Insight: Retail/Trade\n\n**Key metric:** Inventory turnover = (Cost of Goods Sold) ÷ (Average Inventory Value). Target: 4-12x/year. Dead inventory is dead cash — discount and move it.\n\n**Competitive edge:** Customer experience and location are your moats. Invest in staff training and store presentation.",
        "Food & Beverage": "### Industry Insight: Food & Beverage\n\n**Key metrics:** Food cost % (target: 28-35%), Labor cost % (target: 25-35%), Table turnover rate.\n\n**Survival tactics:** Track waste religiously — spoilage kills margins. Use menu engineering to push high-margin items. Consider delivery or catering to diversify revenue.\n\n**Competitive edge:** Consistency and word-of-mouth. One bad experience can cost you 10 customers.",
        "Professional Services": "### Industry Insight: Professional Services\n\n**Key metric:** Utilization rate — target 60-75% of time on billable work. Below that and you're over-delivering on admin. Above and you're likely burning out.\n\n**Pricing strategy:** Value-based pricing beats hourly rates. Package your services (productize). Raise prices 10-15% annually for existing clients.\n\n**Competitive edge:** Expertise and documented results. Build case studies and thought leadership content.",
        "Logistics & Transportation": "### Industry Insight: Logistics & Transportation\n\n**Key metrics:** Load/trip utilization, cost per km/mile, on-time delivery rate.\n\n**Profit levers:** Backhaul revenue (return trips shouldn't be empty), route optimization (fuel is your #2 cost after labor), preventive maintenance (breakdowns kill margins).\n\n**Competitive edge:** Reliability and speed. In logistics, trust trumps price.",
        "Beauty & Personal Care": "### Industry Insight: Beauty & Personal Care\n\n**Key metrics:** Rebooking rate (target: 60%+), retail-to-service revenue ratio, average spend per visit.\n\n**Retention tactics:** Automated booking reminders, loyalty stamp cards, product retail upsells at checkout.\n\n**Competitive edge:** Relationship and results. Clients follow individual stylists and therapists, not brands.",
        "Manufacturing/Production": "### Industry Insight: Manufacturing/Production\n\n**Key metrics:** Production yield rate, cost per unit, equipment downtime %.\n\n**Profit levers:** Reduce waste through process standardization, negotiate bulk input pricing, explore contract manufacturing for others during low seasons.\n\n**Competitive edge:** Quality consistency and delivery reliability.",
    }
    return industry_insights.get(score.industry, "")


def _generate_growth_opportunities(score: BeaconScore) -> str:
    section = "## Growth Opportunities\n\n*You have specific advantages — here's how to maximize them:*\n\n"
    opportunities = []
    if "PRICING_POWER" in score.opportunity_flags:
        opportunities.append("**Pricing Power Advantage**\nYou've demonstrated the ability to raise prices without losing customers. This is rare.\n- Test another 5-10% increase on new customers only\n- Create a \"premium tier\" offering at 30-50% higher price point\n- An extra 5% margin on the same revenue can mean 25-50% more profit")
    if "STRONG_RETENTION" in score.opportunity_flags:
        opportunities.append("**Customer Loyalty Strength**\n70%+ repeat customers is exceptional — most businesses struggle to hit 40%.\n- Launch a formal referral program to monetize your advocates\n- Create a VIP tier for top customers\n- Survey them to understand what keeps them loyal, then systematically do more of it")
    if "ORGANIC_GROWTH" in score.opportunity_flags:
        opportunities.append("**Organic Growth Engine**\nReferrals and word-of-mouth are your primary channel — the most sustainable and cost-effective one available.\n- Systematize referrals: ask every happy customer for 2-3 introductions\n- Build strategic partnerships with complementary businesses\n- Amplify social proof through reviews, testimonials, and before/afters")
    if "SYSTEMS_READY" in score.opportunity_flags:
        opportunities.append("**Systems & Documentation**\nComprehensive process documentation puts you ahead of 90% of SMEs at your stage.\n- You're ready to scale — hire, franchise, or partner — without breaking the business\n- Use documentation to onboard new staff in days, not months\n- Documented businesses are worth 2-3x more in any acquisition or investment conversation")
    if "FINANCIAL_DISCIPLINE" in score.opportunity_flags:
        opportunities.append("**Financial Discipline**\nStrong financial management (80%+ score) is the foundation for everything else.\n- You can confidently take calculated risks: new locations, products, or key hires\n- Approach banks or investors for growth capital with credible, trackable financials\n- Negotiate better terms with suppliers based on your track record of timely payment")
    section += "\n\n".join(opportunities)
    return section


def _generate_next_steps(score: BeaconScore) -> str:
    section = "## Your Next Steps\n\n"
    if score.total_score >= 70:
        section += "### Immediate Actions (This Week):\n1. Schedule a 2-3 hour strategic planning session to map your 6-month roadmap\n2. Review your top opportunities from this assessment and pick ONE to execute\n3. Build or refine your financial dashboard — track the metrics that matter most\n\n### 30-Day Focus:\nYour business is stable enough to think strategically. Pick ONE growth lever from the opportunities above and run a pilot test within 30 days."
    elif score.total_score >= 50:
        section += "### Immediate Actions (This Week):\n1. Address your #1 critical priority (if flagged) before anything else\n2. Set up basic financial tracking — cash flow and P&L at minimum\n3. Choose ONE weakness to fix and commit to it for the next 30 days\n4. Schedule a 15-minute weekly progress check-in with yourself every Friday\n\n### 30-Day Focus:\nStabilize your weakest category. Don't chase growth until you've shored up the foundation. Consistency beats intensity."
    else:
        section += "### Immediate Actions (This Week):\n1. CASH FIRST — if you have <30 days runway, everything else waits\n2. Cut non-essentials to reduce burn by at least 20%\n3. Call every late-paying customer today\n4. Seek outside perspective — you need a fresh set of eyes to turn this around\n\n### 30-Day Focus:\nSurvival mode. Extend runway and stabilize operations. Stop the bleeding before any growth moves."
    section += f"\n\n---\n\n### How BeamX Can Help\n\nBased on your {score.readiness_level} assessment:\n\n"
    if score.total_score >= 70:
        section += "**For Stable & Scale-Ready Businesses:** Strategic advisory for growth planning, advanced analytics, partnership and investor readiness preparation.\n\n**Recommended:** Strategic Advisory Retainer or Growth Acceleration Package"
    elif score.total_score >= 50:
        section += "**For Building Businesses:** Financial visibility, process systematization, marketing efficiency audits, team productivity frameworks.\n\n**Recommended:** 90-Day Business Transformation Program"
    else:
        section += "**For Survival-Mode Businesses:** Emergency cash flow rescue planning, rapid diagnostic consulting, margin analysis and quick-win identification.\n\n**Recommended:** Business Rescue Intensive (4-week program)"
    section += "\n\nBook a free 30-minute strategy call: https://calendly.com/beamxsolutions"
    return section


def build_structured_advisory(score: BeaconScore) -> str:
    sections = [_generate_executive_summary(score)]

    if score.critical_flags:
        sections.append(_generate_critical_priorities(score))

    categories = sorted([
        (score.financial_health.percentage, "Financial Health", score.financial_health),
        (score.customer_strength.percentage, "Customer Strength", score.customer_strength),
        (score.operational_maturity.percentage, "Operational Maturity", score.operational_maturity),
        (score.financial_intelligence.percentage, "Financial Intelligence", score.financial_intelligence),
        (score.growth_resilience.percentage, "Growth & Resilience", score.growth_resilience),
    ], key=lambda x: x[0])

    recs_section = "## Strategic Recommendations\n\n*Focus areas to strengthen your business over the next 90 days.*\n\n"
    recs_section += _get_category_recommendation(categories[0][1], categories[0][2], score)
    if categories[1][0] < 60:
        recs_section += "\n\n" + _get_category_recommendation(categories[1][1], categories[1][2], score)
    pain_rec = _get_pain_point_recommendation(score)
    if pain_rec:
        recs_section += "\n\n" + pain_rec
    industry_rec = _get_industry_recommendation(score)
    if industry_rec:
        recs_section += "\n\n" + industry_rec
    sections.append(recs_section)

    if score.opportunity_flags:
        sections.append(_generate_growth_opportunities(score))

    sections.append(_generate_next_steps(score))
    return "\n\n---\n\n".join(sections)


# ─────────────────────────────────────────────
# STEP 2: LLM NARRATIVE POLISH
# ─────────────────────────────────────────────

async def polish_advisory_with_llm(structured_advisory: str, score: BeaconScore, owner_name: str, business_name: str) -> str:
    system_prompt = """You are a senior business advisor at BeamX Solutions — direct, warm, and sharp.
Your job is to rewrite a structured business assessment advisory in a natural, engaging voice.

CRITICAL RULES:
- Do NOT change any scores, grades, percentages, or numerical data
- Do NOT invent new recommendations — only rewrite what is provided
- Do NOT remove any sections — every section must be present in your output
- Do NOT use generic corporate language. Write like a trusted advisor talking directly to this person
- DO use the owner's first name naturally — once or twice per section, not every sentence
- DO preserve all markdown formatting (##, ###, **, bullet points)
- DO be warm but honest — don't sugarcoat real problems, but don't catastrophize either
- DO maintain approximately the same length — this is a full advisory, not a summary
- DO write in second person ("you", "your business") throughout"""

    user_prompt = f"""Please rewrite the following business assessment advisory for {owner_name}, owner of {business_name}.
They scored {score.total_score}/100 and are at the "{score.readiness_level}" stage.
Their primary challenge: "{score.primary_pain_point}"
Industry: {score.industry} | Years in Business: {score.years_in_business}

Rewrite this in a warm, direct, personalized voice. Every fact, number, score, and recommendation must stay exactly as-is — only the tone and phrasing should change.

---

{structured_advisory}"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=2500,
            temperature=0.7,
        )
        polished = response.choices[0].message.content.strip()
        logger.info(f"LLM polish completed for {owner_name} at {business_name}")
        return polished
    except Exception as e:
        logger.error(f"LLM polish failed — falling back to structured advisory: {e}")
        return structured_advisory


# ─────────────────────────────────────────────
# PDF GENERATION
# ─────────────────────────────────────────────

def generate_pdf_report(score: BeaconScore, data: BeaconSMEInput, advisory: str) -> io.BytesIO:
    logo_url = 'https://beamxsolutions.com/Beamx-Logo-Colour.png'
    cover_bg_url = 'https://beamxsolutions.com/front-background.PNG'
    cta_img_url = 'https://beamxsolutions.com/cta-image.png'
    generated_date = datetime.datetime.now().strftime('%B %d, %Y')

    def md_to_html(text: str) -> str:
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        lines = text.split('\n')
        html_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith('## '):
                html_lines.append(f'<h2 style="color:#0066cc;font-size:17px;margin:16px 0 8px;border-bottom:2px solid #0066cc;padding-bottom:4px;">{line[3:]}</h2>')
            elif line.startswith('### '):
                html_lines.append(f'<h3 style="color:#FF8C00;font-size:14px;margin:12px 0 6px;">{line[4:]}</h3>')
            elif line.startswith('- ') or line.startswith('• '):
                html_lines.append(f'<li style="margin:5px 0;line-height:1.5;font-size:12px;">{line[2:]}</li>')
            elif line == '---':
                html_lines.append('<hr style="border:1px solid #ddd;margin:16px 0;">')
            else:
                html_lines.append(f'<p style="margin:5px 0;line-height:1.5;font-size:12px;">{line}</p>')
        return '\n'.join(html_lines)

    advisory_html = md_to_html(advisory)

    def score_bar(pct):
        color = "#0066cc" if pct >= 70 else "#FF8C00" if pct >= 50 else "#cc3300"
        return f'<div style="background:#eee;border-radius:4px;height:10px;width:100%;"><div style="background:{color};width:{pct}%;height:10px;border-radius:4px;"></div></div>'

    categories = [score.financial_health, score.customer_strength, score.operational_maturity,
                  score.financial_intelligence, score.growth_resilience]
    table_rows = "".join([f'<tr><td style="padding:10px;border:1px solid #ddd;">{c.name}</td><td style="padding:10px;border:1px solid #ddd;text-align:center;font-weight:bold;">{c.score}</td><td style="padding:10px;border:1px solid #ddd;text-align:center;">20</td><td style="padding:10px;border:1px solid #ddd;text-align:center;font-weight:bold;">{c.grade}</td><td style="padding:10px;border:1px solid #ddd;">{score_bar(c.percentage)}</td></tr>' for c in categories])

    insights_parts = []
    for c in categories:
        if c.insights:
            lis = "".join([f'<li style="margin:3px 0;font-size:11px;line-height:1.5;">{i}</li>' for i in c.insights])
            insights_parts.append(f'<h3 style="color:#FF8C00;margin:12px 0 5px;font-size:13px;">{c.name}</h3><ul style="margin:0;padding-left:18px;">{lis}</ul>')
    insights_html = "".join(insights_parts)

    circumference = 2 * 3.14159 * 70
    progress = (score.total_score / 100) * circumference

    html_content = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  @page {{ size: letter; margin: 0; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: Arial, sans-serif; background: #f5f5f5; color: #000; }}
  .page {{ width:8.5in; min-height:11in; background:white; position:relative; page-break-after:always; }}
  .page-cover {{ background-image:url('{cover_bg_url}'); background-size:cover; background-position:center; display:flex; flex-direction:column; justify-content:space-between; height:11in; }}
  .page-content {{ padding:40px 50px 80px; background:#f5f5f5; }}
  .footer {{ background:#0066cc; color:white; padding:12px 50px; display:flex; justify-content:space-between; font-size:11px; position:absolute; bottom:0; left:0; right:0; }}
  table {{ width:100%; border-collapse:collapse; background:white; }}
  th {{ background:#FF8C00; color:white; padding:10px; text-align:center; font-size:12px; }}
</style>
</head><body>

<div class="page page-cover">
  <div style="padding:40px 60px;"><img src="{logo_url}" style="width:180px;" /></div>
  <div style="background:rgba(0,51,153,0.95);padding:80px 60px;">
    <h1 style="font-size:60px;font-weight:bold;color:white;line-height:1.1;">Beacon<br>Business<br>Assessment</h1>
  </div>
  <div style="padding:40px 60px;color:white;">
    <p style="font-weight:600;margin-bottom:4px;">Prepared For</p>
    <p style="font-size:20px;margin-bottom:4px;">{data.fullName}</p>
    <p style="font-size:13px;margin-bottom:16px;">{data.email}</p>
    <p style="font-weight:600;margin-bottom:4px;">Business</p>
    <p style="font-size:16px;margin-bottom:16px;">{data.businessName}</p>
    <p style="font-weight:600;margin-bottom:4px;">Generated on</p>
    <p style="font-size:15px;">{generated_date}</p>
  </div>
</div>

<div class="page page-content">
  <h2 style="color:#0066cc;font-size:20px;font-weight:bold;border-bottom:3px solid #0066cc;display:inline-block;padding-bottom:4px;margin-bottom:20px;">Overall Assessment</h2>
  <div style="display:flex;gap:24px;align-items:center;background:white;padding:20px;margin-bottom:20px;">
    <svg width="160" height="160" viewBox="0 0 200 200">
      <circle cx="100" cy="100" r="70" fill="none" stroke="#FF8C00" stroke-width="28"/>
      <circle cx="100" cy="100" r="70" fill="none" stroke="#0066cc" stroke-width="28" stroke-dasharray="{progress:.1f} {circumference:.1f}" transform="rotate(-90 100 100)"/>
      <text x="100" y="94" text-anchor="middle" font-size="20" font-weight="bold" fill="#000">{score.total_score}/100</text>
      <text x="100" y="114" text-anchor="middle" font-size="10" fill="#666">Overall Score</text>
    </svg>
    <div>
      <p style="font-size:18px;font-weight:bold;margin-bottom:6px;">Readiness Level</p>
      <p style="font-size:15px;color:#0066cc;margin-bottom:12px;">{score.readiness_level}</p>
      <p style="font-size:12px;margin-bottom:3px;"><strong>Business:</strong> {data.businessName}</p>
      <p style="font-size:12px;margin-bottom:3px;"><strong>Industry:</strong> {data.industry}</p>
      <p style="font-size:12px;margin-bottom:3px;"><strong>Years in Business:</strong> {data.yearsInBusiness}</p>
      <p style="font-size:12px;"><strong>Primary Challenge:</strong> {data.primaryPainPoint}</p>
    </div>
  </div>
  <h2 style="color:#0066cc;font-size:16px;font-weight:bold;border-bottom:2px solid #0066cc;display:inline-block;padding-bottom:3px;margin-bottom:12px;">Score Breakdown</h2>
  <table style="margin-bottom:20px;"><thead><tr><th>Category</th><th>Score</th><th>Max</th><th>Grade</th><th>Performance</th></tr></thead><tbody>{table_rows}</tbody></table>
  <div style="display:flex;gap:14px;">
    <div style="flex:1;background:#fee;border-left:4px solid #cc3300;padding:14px;border-radius:4px;">
      <p style="font-weight:bold;color:#cc3300;margin-bottom:8px;font-size:12px;">Critical Flags</p>
      {''.join([f'<p style="font-size:11px;margin:3px 0;">⚠ {f.replace("_"," ")}</p>' for f in score.critical_flags]) if score.critical_flags else '<p style="font-size:11px;">None detected</p>'}
    </div>
    <div style="flex:1;background:#efe;border-left:4px solid #007700;padding:14px;border-radius:4px;">
      <p style="font-weight:bold;color:#007700;margin-bottom:8px;font-size:12px;">Opportunity Flags</p>
      {''.join([f'<p style="font-size:11px;margin:3px 0;">✓ {f.replace("_"," ")}</p>' for f in score.opportunity_flags]) if score.opportunity_flags else '<p style="font-size:11px;">None detected</p>'}
    </div>
  </div>
  <div class="footer"><span>Beacon Assessment — {data.businessName}</span><span>Copyright © 2025 BeamX Solutions</span></div>
</div>

<div class="page page-content">
  <h2 style="color:#0066cc;font-size:20px;font-weight:bold;border-bottom:3px solid #0066cc;display:inline-block;padding-bottom:4px;margin-bottom:20px;">Category Insights</h2>
  <div style="background:white;padding:20px;">{insights_html}</div>
  <div class="footer"><span>Beacon Assessment — {data.businessName}</span><span>Copyright © 2025 BeamX Solutions</span></div>
</div>

<div class="page page-content">
  <h2 style="color:#0066cc;font-size:20px;font-weight:bold;border-bottom:3px solid #0066cc;display:inline-block;padding-bottom:4px;margin-bottom:20px;">Strategic Advisory</h2>
  <div style="background:white;padding:20px;">{advisory_html}</div>
  <div class="footer"><span>Beacon Assessment — {data.businessName}</span><span>Copyright © 2025 BeamX Solutions</span></div>
</div>

<div class="page" style="background:#0066cc;padding:60px;color:white;height:11in;">
  <h2 style="font-size:34px;font-weight:bold;border-bottom:4px solid #FF8C00;display:inline-block;padding-bottom:8px;margin-bottom:28px;">Ready to Take Action?</h2>
  <div style="background:white;color:#333;padding:20px;border-radius:8px;margin-bottom:28px;font-size:14px;line-height:1.6;">
    Based on your Beacon assessment, BeamX Solutions can help you implement these recommendations and accelerate your path to growth.
  </div>
  <img src="{cta_img_url}" style="width:100%;height:360px;object-fit:cover;border-radius:8px;margin-bottom:28px;" />
  <div style="font-size:15px;line-height:2.4;">
    <p>🌐 www.beamxsolutions.com</p>
    <p>✉️ info@beamxsolutions.com</p>
    <p>📅 https://calendly.com/beamxsolutions</p>
  </div>
</div>

</body></html>'''

    buffer = io.BytesIO()
    HTML(string=html_content).write_pdf(buffer, font_config=FontConfiguration())
    buffer.seek(0)
    return buffer


# ─────────────────────────────────────────────
# EMAIL HELPER
# ─────────────────────────────────────────────

def _build_email_html(data: BeaconSMEInput, score: BeaconScore) -> str:
    return f"""<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:0;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px 0;">
<table width="600" cellpadding="0" cellspacing="0">
  <tr><td style="background:#02428e;padding:40px 20px;text-align:center;">
    <img src="https://beamxsolutions.com/asset-1-2.png" width="112" height="50" style="display:block;margin:0 auto 20px;" />
    <h1 style="color:white;font-size:26px;margin:0;">Your Beacon Assessment Results</h1>
  </td></tr>
  <tr><td style="height:20px;background:#f5f5f5;"></td></tr>
  <tr><td style="padding:0 30px;background:#f5f5f5;">
    <p style="font-size:14px;line-height:1.6;">Hello {data.fullName},<br><br>
    Thank you for completing the Beacon Business Assessment for <strong>{data.businessName}</strong>. Your personalized report is attached to this email.</p>
  </td></tr>
  <tr><td style="height:16px;background:#f5f5f5;"></td></tr>
  <tr><td align="center" style="background:#f5f5f5;">
    <table width="380" cellpadding="22" cellspacing="0" style="background:#008bd8;border-radius:8px;">
      <tr><td>
        <p style="color:white;font-size:20px;font-weight:700;margin:0;">Score: {score.total_score}/100</p>
        <p style="color:white;font-size:13px;margin:6px 0 0;">Readiness Level: {score.readiness_level}</p>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="height:16px;background:#f5f5f5;"></td></tr>
  <tr><td style="padding:0 30px;background:#f5f5f5;">
    <table width="100%" cellpadding="16" cellspacing="0" style="background:white;border-radius:8px;">
      <tr><td>
        <h2 style="color:#008bd8;font-size:15px;margin:0 0 14px;">Score Breakdown</h2>
        <p style="font-size:13px;margin:0 0 8px;">💰 Financial Health: <strong>{score.financial_health.score}/20</strong> — {score.financial_health.grade}</p>
        <p style="font-size:13px;margin:0 0 8px;">🤝 Customer Strength: <strong>{score.customer_strength.score}/20</strong> — {score.customer_strength.grade}</p>
        <p style="font-size:13px;margin:0 0 8px;">⚙️ Operational Maturity: <strong>{score.operational_maturity.score}/20</strong> — {score.operational_maturity.grade}</p>
        <p style="font-size:13px;margin:0 0 8px;">📊 Financial Intelligence: <strong>{score.financial_intelligence.score}/20</strong> — {score.financial_intelligence.grade}</p>
        <p style="font-size:13px;margin:0;">📈 Growth & Resilience: <strong>{score.growth_resilience.score}/20</strong> — {score.growth_resilience.grade}</p>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="height:16px;background:#f5f5f5;"></td></tr>
  <tr><td style="padding:0 30px;background:#f5f5f5;">
    <p style="font-size:13px;line-height:1.6;">Your full strategic advisory — including critical priorities, 90-day action plans, and growth opportunities specific to your business — is in the attached PDF.</p>
  </td></tr>
  <tr><td style="height:16px;background:#f5f5f5;"></td></tr>
  <tr><td align="center" style="background:#f5f5f5;">
    <table cellpadding="0" cellspacing="0"><tr>
      <td style="background:#f27900;border-radius:8px;">
        <a href="https://calendly.com/beamxsolutions" style="display:inline-block;padding:13px 26px;color:white;text-decoration:none;font-size:14px;font-weight:700;">Book Your Free Strategy Call</a>
      </td>
    </tr></table>
  </td></tr>
  <tr><td style="height:16px;background:#f5f5f5;"></td></tr>
  <tr><td style="background:#02428e;padding:20px;text-align:center;">
    <p style="color:white;font-size:12px;margin:0 0 6px;">www.beamxsolutions.com | info@beamxsolutions.com</p>
    <p style="color:white;font-size:11px;margin:0;">Copyright © 2025 BeamX Solutions</p>
  </td></tr>
</table></td></tr></table>
</body>"""


def send_results_email(data: BeaconSMEInput, score: BeaconScore, advisory: str) -> bool:
    if not resend_api_key:
        logger.warning("Resend not configured. Skipping email.")
        return False
    try:
        pdf_buffer = generate_pdf_report(score, data, advisory)
        pdf_b64 = base64.b64encode(pdf_buffer.read()).decode()

        resend.Emails.send({
            "from": f"BeamX Solutions <{from_email}>",
            "to": [data.email],
            "subject": f"Your Beacon Report: {score.total_score}/100 — {score.readiness_level} | {data.businessName}",
            "html": _build_email_html(data, score),
            "attachments": [{"filename": "Beacon_Assessment_Report.pdf", "content": pdf_b64}]
        })
        logger.info(f"Email sent to {data.email}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False


# ─────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────

@app.post("/download-pdf")
async def download_pdf(payload: dict):
    """Generate and return PDF for direct browser download"""
    try:
        form_data = BeaconSMEInput(**payload["formData"])
        score = calculate_beacon_score(form_data)
        # Use advisory from the result payload if available, otherwise rebuild (no LLM)
        advisory = payload.get("result", {}).get("advisory") or build_structured_advisory(score)
        pdf_buffer = generate_pdf_report(score, form_data, advisory)
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Beacon_Assessment_{form_data.businessName.replace(' ', '_')}.pdf"}
        )
    except Exception as e:
        logger.error(f"PDF download error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-report")
async def generate_report(input_data: BeaconSMEInput):
    try:
        # Step 1: Score
        score = calculate_beacon_score(input_data)
        logger.info(f"Score: {score.total_score}/100 for {input_data.businessName}")

        # Step 2: Build structured advisory (rule-based)
        structured_advisory = build_structured_advisory(score)
        logger.info("Rule-based advisory built")

        # Step 3: Polish with LLM (narrative + personalization layer)
        advisory = await polish_advisory_with_llm(
            structured_advisory, score, input_data.fullName, input_data.businessName
        )
        logger.info("LLM polish complete")

        result = {
            "total_score": score.total_score,
            "readiness_level": score.readiness_level,
            "breakdown": {
                "financial_health": {"score": score.financial_health.score, "max": 20, "grade": score.financial_health.grade, "percentage": score.financial_health.percentage, "insights": score.financial_health.insights},
                "customer_strength": {"score": score.customer_strength.score, "max": 20, "grade": score.customer_strength.grade, "percentage": score.customer_strength.percentage, "insights": score.customer_strength.insights},
                "operational_maturity": {"score": score.operational_maturity.score, "max": 20, "grade": score.operational_maturity.grade, "percentage": score.operational_maturity.percentage, "insights": score.operational_maturity.insights},
                "financial_intelligence": {"score": score.financial_intelligence.score, "max": 20, "grade": score.financial_intelligence.grade, "percentage": score.financial_intelligence.percentage, "insights": score.financial_intelligence.insights},
                "growth_resilience": {"score": score.growth_resilience.score, "max": 20, "grade": score.growth_resilience.grade, "percentage": score.growth_resilience.percentage, "insights": score.growth_resilience.insights},
            },
            "flags": {"critical": score.critical_flags, "opportunities": score.opportunity_flags},
            "advisory": advisory,
            "context": {
                "industry": input_data.industry,
                "yearsInBusiness": input_data.yearsInBusiness,
                "primaryPainPoint": input_data.primaryPainPoint,
                "businessName": input_data.businessName,
            }
        }

        # Save to Supabase
        try:
            supabase.table("beacon_assessments").insert({
                **input_data.model_dump(),
                "total_score": score.total_score,
                "readiness_level": score.readiness_level,
                "critical_flags": score.critical_flags,
                "opportunity_flags": score.opportunity_flags,
                "advisory": advisory,
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()
        except Exception as db_err:
            logger.warning(f"DB insert failed (non-fatal): {db_err}")

        email_sent = send_results_email(input_data, score, advisory)
        result["email_sent"] = email_sent
        return result

    except Exception as e:
        logger.error(f"Report generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/email-results")
async def email_results(payload: dict):
    """
    Send the PDF report to any email address the user specifies.
    Frontend sends: { email: str, result: BeaconResult, formData: dict }

    KEY CHANGE: We reuse result.advisory from the frontend payload instead of
    re-running the LLM pipeline. This cuts response time from ~45s down to ~5s,
    preventing frontend timeout false-errors.
    """
    try:
        recipient_email = payload.get("email")
        if not recipient_email:
            raise HTTPException(status_code=400, detail="Email address is required")

        form_data = BeaconSMEInput(**payload["formData"])
        score = calculate_beacon_score(form_data)

        # ✅ Reuse the advisory already generated and returned to the frontend.
        # This avoids a redundant GPT-4 call and makes this endpoint ~10x faster.
        advisory = payload.get("result", {}).get("advisory")
        if not advisory:
            # Fallback: rebuild without LLM polish (instant, rule-based only)
            logger.warning("No advisory found in payload — falling back to rule-based advisory")
            advisory = build_structured_advisory(score)

        if not resend_api_key:
            raise HTTPException(status_code=500, detail="Email not configured on server. RESEND_API_KEY is missing.")

        # Generate PDF and send to the recipient email
        form_data_for_email = form_data.model_copy(update={"email": recipient_email})
        pdf_buffer = generate_pdf_report(score, form_data_for_email, advisory)
        pdf_b64 = base64.b64encode(pdf_buffer.read()).decode()

        response = resend.Emails.send({
            "from": f"BeamX Solutions <{from_email}>",
            "to": [recipient_email],
            "subject": f"Your Beacon Report: {score.total_score}/100 — {score.readiness_level} | {form_data.businessName}",
            "html": _build_email_html(form_data_for_email, score),
            "attachments": [{"filename": "Beacon_Assessment_Report.pdf", "content": pdf_b64}]
        })

        logger.info(f"Email sent to {recipient_email}, Resend ID: {getattr(response, 'id', 'unknown')}")
        return {"status": "success", "message": f"Report sent to {recipient_email}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Email results error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Email failed: {str(e)}")


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "3.0.0", "tool": "Beacon", "architecture": "rules + LLM polish"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))