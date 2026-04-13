"""
Report Agent - generates the final human-readable shopping recommendation.
"""
import json
from anthropic import Anthropic

client = Anthropic()

REPORT_SYSTEM = """You are a friendly grocery shopping advisor for Indian customers.
Create a clear, concise shopping recommendation report from the analysis data.

Format your response as a structured text report with:
- A summary header with total savings
- Per-item best deal recommendations
- Store consolidation plan
- Money-saving tips based on the deals found

Use ₹ for currency. Keep it practical and easy to follow.
Use emojis sparingly for readability (🛒 🏷️ ⚡ 💰 📦).
"""


def generate_report(items: list[dict], price_data: list[dict], analysis: dict) -> str:
    """Generate final shopping report using LLM."""

    prompt = f"""
Generate a shopping recommendation report based on this analysis:

Analysis Data:
{json.dumps(analysis, indent=2)}

Number of items: {len(items)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=REPORT_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text
