# 🛒 Grocery Price Comparison Agent

A multi-agent system that compares grocery prices across **Blinkit**, **Zepto**, **BigBasket**, and **Amazon Fresh** — then recommends the best deals for your monthly shopping.

## Architecture

```
User Input (Grocery List)
        │
        ▼
┌─────────────────────┐
│  Orchestrator Agent │  ← Parses list, coordinates all agents
└─────────────────────┘
        │
        ▼ (for each item, all stores scraped concurrently)
┌────────────────────────────────────────────────────────────────┐
│                    Store Scraper Agents                        │
│  ┌─────────────────┐  ┌─────────────────┐                     │
│  │    Blinkit       │  │     Zepto        │  ← Apify Actors    │
│  │    (Apify)      │  │    (Apify)      │    (pay-per-event)  │
│  └─────────────────┘  └─────────────────┘                     │
│  ┌─────────────────┐  ┌─────────────────┐                     │
│  │   BigBasket      │  │  Amazon Fresh   │  ← Direct HTTP      │
│  │  (httpx / LLM)  │  │  (httpx / LLM)  │    scrapers         │
│  └─────────────────┘  └─────────────────┘                     │
└────────────────────────────────────────────────────────────────┘
        │  Blinkit/Zepto: marked unavailable on failure (no LLM)
        │  BigBasket/Amazon Fresh: fall back to LLM on failure
        ▼
┌─────────────────────┐
│  Deal Analyst Agent │  ← Scores & picks best deal per item
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│   Report Agent      │  ← Generates final recommendation
└─────────────────────┘
        │
        ▼
  Shopping Report +
  Price Breakdown Table
```

## Data Sources

| Store | Method | Cost | Notes |
|-------|--------|------|-------|
| Blinkit | Apify Actor `krazee_kaushik/blinkit-search-results-scraper` | Pay-per-event | Needs `APIFY_API_TOKEN` |
| Zepto | Apify Actor `krazee_kaushik/zepto-scraper` | Pay-per-event | Needs `APIFY_API_TOKEN` |
| BigBasket | Direct `httpx` scraper (BB search page) | Free | No auth needed; falls back to LLM on failure |
| Amazon Fresh | Direct `httpx` scraper (Amazon.in search) | Free | No auth needed; falls back to LLM on failure |

Blinkit and Zepto return **unavailable** (no price) if the Apify run fails — no LLM estimates are used for them. BigBasket and Amazon Fresh fall back to LLM estimates on network/parse errors.

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set environment variables
```bash
cp .env.example .env
# Edit .env and fill in your keys
source .env
```

Key variables:
- `ANTHROPIC_API_KEY` — required for all LLM agents
- `APIFY_API_TOKEN` — needed for Blinkit & Zepto real data. Free account at https://console.apify.com

### 3. (Optional) Set your city
By default the agent uses Kolkata. Change via env vars:
```bash
export LOCATION_LAT=12.9716       # Bengaluru (used by Blinkit & Zepto)
export LOCATION_LNG=77.5946
export BB_CITY_ID=10              # BigBasket: 10=Bengaluru, 3=Mumbai, 4=Delhi, 8=Kolkata
export AMAZON_PINCODE=560001
```

## Usage

### Run with the built-in sample grocery list
```bash
python main.py
```

### Run with your own grocery list
```bash
python main.py "2kg Rice, 1L Milk, 500g Dal, 1 dozen eggs, 200g Butter"
```

### Run with a grocery list from a file
```bash
python main.py my_grocery_list.txt
```

## Output

1. **Live console output** showing each agent's progress and data source
2. **Final report** with per-item best deal recommendations
3. **Price summary table** comparing all stores
4. **Store consolidation plan** to minimise delivery orders
5. **`grocery_report.json`** with full raw data for further processing

## Agents

| Agent | Role |
|-------|------|
| `Orchestrator` | Parses grocery list, coordinates pipeline |
| `Store Scrapers` | 4 parallel scrapers (Blinkit, Zepto, BigBasket, Amazon Fresh) |
| `Deal Analyst` | Scores deals, picks best option per item |
| `Report Agent` | Generates human-readable final recommendation |

## Test Output

(grocery_deal_finder) (base) grocery_deal_finder % python main.py "1kg Basmati Rice, 500g Dal, 2L Milk, 1 dozen eggs"

╔══════════════════════════════════════════════════════════╗
║       🛒  GROCERY PRICE COMPARISON AGENT  🛒             ║
║   Blinkit | BigBasket | Flipkart Minutes | Amazon Fresh  ║
╚══════════════════════════════════════════════════════════╝


📋 Grocery List:
1kg Basmati Rice, 500g Dal, 2L Milk, 1 dozen eggs

============================================================

[Orchestrator] Parsing grocery list...
[Orchestrator] Found 4 items: ['Basmati Rice', 'Dal', 'Milk', 'eggs']

[Orchestrator] Dispatching store scraper agents...

  🔍 1 kg  Basmati Rice
  Blinkit              Basmati Rice              ₹795  🏷 20% OFF  [apify]

  🔍 500 g  Dal
  Blinkit              Dal                       ₹176  🏷 29% OFF  [apify]

  🔍 2 L  Milk
  Blinkit              Milk                      ₹53  🏷 10% OFF  [apify]

  🔍 12 pieces  eggs
  Blinkit              eggs                      ₹81  🏷 10% OFF  [apify]

[Orchestrator] Sending data to Deal Analyst agent...
[Deal Analyst] Analysis complete. Total savings: ₹288

[Orchestrator] Generating final report...

============================================================
📊 FINAL RECOMMENDATION REPORT
============================================================
# 🛒 Smart Shopping Report

## **Total Savings Summary**
💰 **You'll save ₹288** (20.7% discount) on your 4-item grocery order!
- **Cart Total:** ₹1,105 (down from MRP ₹1,393)

---

## **Best Deal Recommendations**

### 🏷️ **Basmati Rice** - Blinkit
- **Price:** ₹795 (was ₹995) | **Save:** ₹200 (20% OFF)
- ⚡ Delivery: 10 mins
- Best available option with solid discount

### 🏷️ **Dal** - Blinkit  
- **Price:** ₹176 (was ₹249) | **Save:** ₹73 (29% OFF)
- ⚡ Delivery: 10 mins
- **Highest savings!** Excellent 29% discount

### 🏷️ **Milk** - Blinkit
- **Price:** ₹53 (was ₹59) | **Save:** ₹6 (10% OFF)
- ⚡ Delivery: 10 mins
- Good everyday essential deal

### 🏷️ **Eggs** - Blinkit
- **Price:** ₹81 (was ₹90) | **Save:** ₹9 (10% OFF)
- ⚡ Delivery: 10 mins
- Decent savings on fresh eggs

---

## **📦 Store Consolidation Plan**

**Single Store Shopping:** Order everything from **Blinkit**
- All 4 items available in one place
- Consistent 10-minute fast delivery
- No need to juggle multiple orders or delivery times

---

## **Money-Saving Tips**

✅ **Order all items together** from Blinkit to save on multiple delivery charges

✅ **Dal offers the best value** - stock up if it's non-perishable

✅ **Quick 10-minute delivery** means you can order fresh items like milk and eggs as needed

✅ **20.7% overall savings** - you're getting great value across your entire cart!

**Happy Shopping! Your groceries will arrive in just 10 minutes with significant savings.**

============================================================
📈 QUICK PRICE SUMMARY
============================================================

Item                      Best Store              Price    Saved Deal
--------------------------------------------------------------------------------
Basmati Rice              Blinkit              ₹   795 ₹   200 🏷️ 20% OFF
Dal                       Blinkit              ₹   176 ₹    73 🏷️ 29% OFF
Milk                      Blinkit              ₹    53 ₹     6 🏷️ 10% OFF
eggs                      Blinkit              ₹    81 ₹     9 🏷️ 10% OFF
--------------------------------------------------------------------------------
TOTAL                     (optimized cart)     ₹  1105 ₹   288

💰 You save 20.7% vs buying at MRP!

📦 Recommended Stores: Blinkit
   Blinkit: Basmati Rice, Dal, Milk, eggs

[System] Full data saved to grocery_report.json
