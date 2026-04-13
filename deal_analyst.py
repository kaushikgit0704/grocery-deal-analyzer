"""
Deal Analyst Agent - compares prices across stores and picks the best deal per item.
Also suggests store consolidation to minimize deliveries.
"""
import json
from anthropic import Anthropic

client = Anthropic()

ANALYST_SYSTEM = """You are a smart grocery deal analyst for Indian shoppers.
Given price data from multiple stores, you must:
1. For each item, identify the BEST deal (lowest price + best discount + delivery speed)
2. Suggest store consolidation (fewer stores = fewer deliveries)
3. Calculate total savings vs buying everything at MRP

Scoring formula (use internally):
- Price score: lower is better (40% weight)
- Discount score: higher % is better (30% weight)  
- Delivery speed score: faster is better (20% weight)
- Deal/offer bonus (10% weight)

Respond ONLY with valid JSON — no markdown, no explanation:
{
  "item_recommendations": [
    {
      "item": "item name",
      "best_store": "store name",
      "best_price": 99.0,
      "best_mrp": 120.0,
      "savings": 21.0,
      "savings_percent": 17.5,
      "deal": "deal description or null",
      "delivery_time": "10 mins",
      "reason": "brief reason for selection",
      "runner_up": {"store": "store", "price": 105.0}
    }
  ],
  "consolidation": {
    "recommended_stores": ["Blinkit", "BigBasket"],
    "store_items": {
      "Blinkit": ["item1", "item2"],
      "BigBasket": ["item3"]
    },
    "reason": "explanation of consolidation logic"
  },
  "total_cart_price": 850.0,
  "total_mrp": 1100.0,
  "total_savings": 250.0,
  "overall_savings_percent": 22.7
}
"""


def analyze_deals(items: list[dict], price_data: list[dict]) -> dict:
    """Use LLM to analyze all price data and find best deals."""

    # Format data for the analyst
    summary = []
    for entry in price_data:
        item_summary = {
            "item": entry["item"]["name"],
            "quantity": f"{entry['item']['quantity']} {entry['item']['unit']}",
            "prices": []
        }
        for sp in entry["store_prices"]:
            if sp.get("available", True) and sp.get("price"):
                item_summary["prices"].append({
                    "store": sp["store"],
                    "price": sp["price"],
                    "mrp": sp.get("mrp"),
                    "discount": sp.get("discount_percent", 0),
                    "deal": sp.get("deal"),
                    "delivery": sp.get("delivery_time")
                })
        summary.append(item_summary)

    prompt = f"Analyze these grocery prices and find best deals:\n{json.dumps(summary, indent=2)}"

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=ANALYST_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    analysis = json.loads(raw.strip())
    print(f"[Deal Analyst] Analysis complete. Total savings: ₹{analysis.get('total_savings', 0):.0f}")
    return analysis
