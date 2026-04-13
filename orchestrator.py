"""
Orchestrator Agent - coordinates the multi-agent grocery price comparison workflow.
"""
import asyncio
import json
from typing import Any
from anthropic import Anthropic

client = Anthropic()

ORCHESTRATOR_SYSTEM = """You are a grocery shopping orchestrator agent. Your job is to:
1. Parse a grocery list from the user (items + quantities)
2. Coordinate store scraper agents for each item
3. Direct the deal analyst to find the best prices
4. Present a clear, money-saving recommendation

When given a grocery list, extract each item with quantity and unit.
Respond ONLY with valid JSON in this format:
{
  "items": [
    {"name": "item name", "quantity": 1, "unit": "kg/g/L/ml/pieces/pack"},
    ...
  ]
}
"""


def parse_grocery_list(grocery_list: str) -> list[dict]:
    """Use LLM to parse natural language grocery list into structured items."""
    print("\n[Orchestrator] Parsing grocery list...")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=ORCHESTRATOR_SYSTEM,
        messages=[{"role": "user", "content": f"Parse this grocery list:\n{grocery_list}"}]
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    parsed = json.loads(raw.strip())
    items = parsed["items"]
    print(f"[Orchestrator] Found {len(items)} items: {[i['name'] for i in items]}")
    return items


async def run_pipeline(grocery_list: str) -> dict[str, Any]:
    """Main pipeline: parse -> scrape -> analyze -> report."""
    from store_scraper import scrape_all_stores
    from deal_analyst import analyze_deals
    from report_agent import generate_report

    # Step 1: Parse
    items = parse_grocery_list(grocery_list)

    # Step 2: Scrape all stores concurrently
    print("\n[Orchestrator] Dispatching store scraper agents...")
    price_data = await scrape_all_stores(items)

    # Step 3: Analyze deals
    print("\n[Orchestrator] Sending data to Deal Analyst agent...")
    analysis = analyze_deals(items, price_data)

    # Step 4: Generate report
    print("\n[Orchestrator] Generating final report...")
    report = generate_report(items, price_data, analysis)

    return {
        "items": items,
        "price_data": price_data,
        "analysis": analysis,
        "report": report
    }
