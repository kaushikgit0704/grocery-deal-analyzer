"""
Grocery Price Agent - Main Entry Point
Multi-agent workflow: Orchestrator -> Store Scrapers -> Deal Analyst -> Report Agent
"""
import asyncio
import json
import sys
import os

from dotenv import load_dotenv

load_dotenv(override=True)  # Load environment variables from .env file

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestrator import run_pipeline

SAMPLE_GROCERY_LIST = """
- 1 kg Basmati Rice
- 500g Toor Dal
- 2L Amul Full Cream Milk
- 1 dozen eggs
- 200g Amul Butter
- 1kg Onions
- 500g Tomatoes
- 1 bottle Saffola Gold Oil (1L)
- 100g Maggi Masala
- 2 packs Britannia Marie Biscuits
"""

BANNER = """
╔══════════════════════════════════════════════════════════╗
║       🛒  GROCERY PRICE COMPARISON AGENT  🛒             ║
║   Blinkit | BigBasket | Flipkart Minutes | Amazon Fresh  ║
╚══════════════════════════════════════════════════════════╝
"""


def save_results(results: dict, filename: str = "grocery_report.json"):
    """Save full results to JSON for inspection."""
    with open(filename, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[System] Full data saved to {filename}")


async def main():
    print(BANNER)

    # Accept grocery list from argument, file, or use sample
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if os.path.isfile(arg):
            with open(arg) as f:
                grocery_list = f.read()
            print(f"[System] Loaded grocery list from: {arg}")
        else:
            grocery_list = arg
    else:
        print("[System] Using sample grocery list (pass a list as argument or file path)")
        grocery_list = SAMPLE_GROCERY_LIST

    print(f"\n📋 Grocery List:\n{grocery_list}")
    print("\n" + "="*60)

    try:
        results = await run_pipeline(grocery_list)

        print("\n" + "="*60)
        print("📊 FINAL RECOMMENDATION REPORT")
        print("="*60)
        print(results["report"])

        print("\n" + "="*60)
        print("📈 QUICK PRICE SUMMARY")
        print("="*60)

        analysis = results["analysis"]
        print(f"\n{'Item':<25} {'Best Store':<20} {'Price':>8} {'Saved':>8} {'Deal'}")
        print("-"*80)

        for rec in analysis.get("item_recommendations", []):
            deal_str = f"🏷️ {rec['deal'][:25]}" if rec.get("deal") else ""
            print(
                f"{rec['item']:<25} "
                f"{rec['best_store']:<20} "
                f"₹{rec['best_price']:>6.0f} "
                f"₹{rec.get('savings', 0):>6.0f} "
                f"{deal_str}"
            )

        print("-"*80)
        print(
            f"{'TOTAL':<25} "
            f"{'(optimized cart)':<20} "
            f"₹{analysis.get('total_cart_price', 0):>6.0f} "
            f"₹{analysis.get('total_savings', 0):>6.0f}"
        )
        print(f"\n💰 You save {analysis.get('overall_savings_percent', 0):.1f}% vs buying at MRP!")

        consolidation = analysis.get("consolidation", {})
        if consolidation.get("recommended_stores"):
            print(f"\n📦 Recommended Stores: {', '.join(consolidation['recommended_stores'])}")
            for store, store_items in consolidation.get("store_items", {}).items():
                print(f"   {store}: {', '.join(store_items)}")

        save_results(results)

    except KeyboardInterrupt:
        print("\n[System] Interrupted by user.")
    except Exception as e:
        print(f"\n[Error] Pipeline failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
