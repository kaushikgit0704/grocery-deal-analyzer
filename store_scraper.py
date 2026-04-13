"""
Store Scraper Agents — real data from four sources:

  Blinkit          → Apify Actor  (krazee_kaushik/blinkit-search-results-scraper)
  Zepto            → Apify Actor  (krazee_kaushik/zepto-scraper)
  BigBasket        → Direct httpx scraper (BB search, no auth required)
  Amazon Fresh     → Direct httpx scraper (Amazon India product search)

Each scraper returns a normalised dict:
  {store, item, quantity, unit, price, mrp, discount_percent, deal, available,
   delivery_time, product_name, source}

Required env vars:
  ANTHROPIC_API_KEY   — for orchestrator / analyst / report agents
  APIFY_API_TOKEN     — for Blinkit & Zepto actors
                        Free account at https://console.apify.com ($5 free/mo)

Optional location env vars:
  LOCATION_LAT        — latitude  for Blinkit & Zepto (default: 22.5726 = Kolkata)
  LOCATION_LNG        — longitude for Blinkit & Zepto (default: 88.3639 = Kolkata)
  AMAZON_PINCODE      — pincode for Amazon Fresh (default: 700001)
  BB_CITY_ID          — BigBasket city ID (default: 8 = Kolkata)
                        IDs: 10=Bengaluru, 3=Mumbai, 4=Delhi, 8=Kolkata

If APIFY_API_TOKEN is absent OR an Apify scrape fails, the item is marked
unavailable (no LLM estimate). BigBasket/Amazon Fresh fall back to LLM on error.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from anthropic import Anthropic
import httpx

# ──────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────

_anthropic = Anthropic()

DELIVERY_TIMES = {
    "Blinkit": "10 mins",
    "Zepto": "10 mins",
    #TODO: Figure out proxy config
    #"BigBasket": "30–120 mins",
    #"Amazon Fresh": "2–4 hours",
}

STORE_NAMES = list(DELIVERY_TIMES.keys())

_BLINKIT_ACTOR = "krazee_kaushik~blinkit-search-results-scraper"
_ZEPTO_ACTOR   = "krazee_kaushik~zepto-scraper"

_LAT      = float(os.getenv("LOCATION_LAT", "22.5726"))
_LNG      = float(os.getenv("LOCATION_LNG", "88.3639"))
_AMZN_PIN = os.getenv("AMAZON_PINCODE", "700001")
_BB_CITY    = os.getenv("BB_CITY_ID", "8")
_BB_PROXY   = os.getenv("BB_PROXY")     # e.g. http://user:pass@host:port
_AMZN_PROXY = os.getenv("AMZN_PROXY")   # same format

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "application/json, text/plain, */*",
}


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────

def _empty(store: str, item: dict, reason: str = "unavailable") -> dict:
    return {
        "store": store,
        "item": item["name"],
        "quantity": item["quantity"],
        "unit": item["unit"],
        "price": None,
        "mrp": None,
        "discount_percent": 0,
        "deal": None,
        "available": False,
        "delivery_time": DELIVERY_TIMES.get(store, "unknown"),
        "product_name": None,
        "source": "error",
        "error": reason,
    }


def _clean_price(val) -> float | None:
    if val is None:
        return None
    return float(str(val).replace("₹", "").replace(",", "").strip())


def _discount(price, mrp) -> int:
    if mrp and price and mrp > price:
        return round((mrp - price) / mrp * 100)
    return 0


def _log(store: str, item_name: str, price, deal=None, source=""):
    price_str = f"₹{price:.0f}" if price else "N/A"
    deal_str  = f"  🏷 {str(deal)[:35]}" if deal else ""
    src_str   = f"  [{source}]" if source else ""
    print(f"  {store:<20} {item_name:<25} {price_str}{deal_str}{src_str}")


# ──────────────────────────────────────────────────────────
# LLM fallback
# ──────────────────────────────────────────────────────────

_FALLBACK_SYS = """You are a price estimator for Indian grocery stores.
Return ONLY valid JSON, no markdown, no extra text:
{"price": <number>, "mrp": <number>, "discount_percent": <0-40>, "deal": <string or null>, "available": true}
Use realistic 2025 Indian market prices in INR."""


def _llm_fallback(store: str, item: dict) -> dict:
    prompt = (
        f"Estimate realistic 2025 price for "
        f"{item['quantity']} {item['unit']} of \"{item['name']}\" on {store} in India."
    )
    resp = _anthropic.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        system=_FALLBACK_SYS,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = re.sub(r"^```(?:json)?|```$", "", resp.content[0].text.strip(), flags=re.MULTILINE).strip()
    data = json.loads(raw)
    result = {
        "store": store,
        "item": item["name"],
        "quantity": item["quantity"],
        "unit": item["unit"],
        "price": data.get("price"),
        "mrp": data.get("mrp"),
        "discount_percent": data.get("discount_percent", 0),
        "deal": data.get("deal"),
        "available": data.get("available", True),
        "delivery_time": DELIVERY_TIMES[store],
        "product_name": None,
        "source": "llm_estimate",
    }
    _log(store, item["name"], result["price"], result["deal"], "llm")
    return result


# ──────────────────────────────────────────────────────────
# Apify runner (shared by Blinkit + Zepto)
# ──────────────────────────────────────────────────────────

def _apify_run(actor_id: str, payload: dict, timeout: int = 120, memory: int = 256) -> list[dict]:
    """Start an Apify actor run and poll until it finishes or timeout is reached.

    Uses the async /runs endpoint + polling instead of run-sync-get-dataset-items.
    run-sync returns HTTP 400 whenever the actor run itself times out, making it
    impossible to distinguish a real input error from a slow run.  The async
    pattern avoids that: we always get a clean success/failure status.
    """
    token = os.getenv("APIFY_API_TOKEN", "")
    if not token:
        raise RuntimeError("APIFY_API_TOKEN not set")

    base = "https://api.apify.com/v2"
    headers = {"Content-Type": "application/json"}
    # trust_env=False stops httpx from picking up any HTTP_PROXY env var
    with httpx.Client(timeout=30, trust_env=False) as client:
        # 1. Start the run
        resp = client.post(
            f"{base}/acts/{actor_id}/runs",
            params={"token": token, "memory": memory},
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        run = resp.json()["data"]
        run_id     = run["id"]
        dataset_id = run["defaultDatasetId"]

        # 2. Poll until terminal status or timeout
        deadline = timeout  # seconds total budget
        waited   = 0
        poll_interval = 5
        while waited < deadline:
            time.sleep(poll_interval)
            waited += poll_interval
            status_resp = client.get(
                f"{base}/actor-runs/{run_id}",
                params={"token": token},
            )
            status_resp.raise_for_status()
            status = status_resp.json()["data"]["status"]
            if status in ("SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"):
                break

        if status != "SUCCEEDED":
            raise RuntimeError(f"Actor run {run_id} ended with status {status!r}")

        # 3. Fetch dataset items
        items_resp = client.get(
            f"{base}/datasets/{dataset_id}/items",
            params={"token": token},
        )
        items_resp.raise_for_status()
        return items_resp.json() if items_resp.text.strip() else []


# ──────────────────────────────────────────────────────────
# 1. Blinkit  (Apify actor)
# ──────────────────────────────────────────────────────────

def _scrape_blinkit(item: dict) -> dict:
    store = "Blinkit"
    try:
        rows = _apify_run(
            _BLINKIT_ACTOR,
            {
                "searchQueries": [item["name"]],
                "locations": [{"name": "Home", "lat": _LAT, "lng": _LNG}],
                "productsLimit": 5,
            },
        )
        if not rows:
            return _empty(store, item, "no results")

        r     = rows[0]
        price = _clean_price(r.get("price") or r.get("sellingPrice") or r.get("discountedPrice"))
        mrp   = _clean_price(r.get("mrp") or r.get("marketPrice")) or (price * 1.1 if price else None)
        disc  = _discount(price, mrp)
        deal  = r.get("offer_text") or r.get("offer") or r.get("deal") or r.get("tag") or (f"{disc}% off" if disc >= 10 else None)

        result = {
            "store": store, "item": item["name"],
            "quantity": item["quantity"], "unit": item["unit"],
            "price": price, "mrp": mrp, "discount_percent": disc,
            "deal": deal, "available": not r.get("out_of_stock", not bool(price)),
            "delivery_time": r.get("deliveryEta") or r.get("eta") or DELIVERY_TIMES[store],
            "product_name": r.get("name") or r.get("productName"),
            "source": "apify_blinkit",
        }
        _log(store, item["name"], price, deal, "apify")
        return result

    except RuntimeError:
        print(f"  [Blinkit] APIFY_API_TOKEN missing → unavailable")
        return _empty(store, item, "no APIFY_API_TOKEN")
    except Exception as e:
        print(f"  [Blinkit] {e} → unavailable")
        return _empty(store, item, str(e))


# ──────────────────────────────────────────────────────────
# 2. Zepto  (Apify actor)
# ──────────────────────────────────────────────────────────

def _scrape_zepto(item: dict) -> dict:
    store = "Zepto"
    try:
        rows = _apify_run(
            _ZEPTO_ACTOR,
            {
                "searchQueries": [item["name"]],
                "locations": [{"name": "Home", "lat": _LAT, "lng": _LNG}],
                "productsLimit": 5,
            },
            timeout=300,   # actor needs up to ~3 min for session + scrape
            memory=4096,   # actor's required memory
        )
        if not rows:
            return _empty(store, item, "no results")

        r     = rows[0]
        price = _clean_price(r.get("price") or r.get("sellingPrice") or r.get("discountedPrice") or r.get("mrp_price"))
        mrp   = _clean_price(r.get("mrp") or r.get("marketPrice")) or (price * 1.1 if price else None)
        disc  = _discount(price, mrp)
        deal  = r.get("offer_text") or r.get("offer") or r.get("badge") or r.get("deal") or (f"{disc}% off" if disc >= 10 else None)

        result = {
            "store": store, "item": item["name"],
            "quantity": item["quantity"], "unit": item["unit"],
            "price": price, "mrp": mrp, "discount_percent": disc,
            "deal": deal, "available": not r.get("out_of_stock", not bool(price)),
            "delivery_time": r.get("deliveryEta") or r.get("eta") or DELIVERY_TIMES[store],
            "product_name": r.get("name") or r.get("productName"),
            "source": "apify_zepto",
        }
        _log(store, item["name"], price, deal, "apify")
        return result

    except RuntimeError:
        print(f"  [Zepto] APIFY_API_TOKEN missing → unavailable")
        return _empty(store, item, "no APIFY_API_TOKEN")
    except Exception as e:
        print(f"  [Zepto] {e} → unavailable")
        return _empty(store, item, str(e))


# ──────────────────────────────────────────────────────────
# 3. BigBasket  (direct HTTP)
# ──────────────────────────────────────────────────────────
# BB embeds product JSON in __NEXT_DATA__ script block.
# NOTE: BB and Amazon block cloud/datacenter IPs (403).
#   - Works fine from home/office IPs.
#   - On 403, falls back to LLM. Set BB_PROXY env var for real data.

def _scrape_bigbasket(item: dict) -> dict:
    store = "BigBasket"
    try:
        headers = {**_HTTP_HEADERS, "Referer": "https://www.bigbasket.com/"}
        search_url = "https://www.bigbasket.com/ps/"
        params = {"q": item["name"], "nc": "as"}
        proxy = _BB_PROXY if _BB_PROXY else None

        with httpx.Client(timeout=25, follow_redirects=True, proxy=proxy, trust_env=False) as client:
            client.get("https://www.bigbasket.com/", headers=headers)
            resp = client.get(search_url, params=params, headers=headers)

        if resp.status_code == 403:
            print(f"  [BigBasket] 403 blocked (set BB_PROXY for real data) → LLM fallback")
            return _llm_fallback(store, item)

        html = resp.text

        # Extract __NEXT_DATA__ JSON
        nd_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if nd_match:
            page_data = json.loads(nd_match.group(1))
            # Drill into nested structure: pageProps → data → products
            try:
                products = (
                    page_data["props"]["pageProps"]["data"]["tabs"][0]["product_info"]["products"]
                )
            except (KeyError, IndexError, TypeError):
                products = []

            if products:
                p     = products[0]
                price = _clean_price(p.get("sp") or p.get("price"))
                mrp   = _clean_price(p.get("mrp")) or (price * 1.1 if price else None)
                disc  = _discount(price, mrp)
                offer = p.get("offer_msg") or (f"{disc}% off" if disc >= 10 else None)

                result = {
                    "store": store, "item": item["name"],
                    "quantity": item["quantity"], "unit": item["unit"],
                    "price": price, "mrp": mrp, "discount_percent": disc,
                    "deal": offer, "available": bool(price),
                    "delivery_time": DELIVERY_TIMES[store],
                    "product_name": p.get("name") or p.get("prod_name"),
                    "source": "direct_bigbasket",
                }
                _log(store, item["name"], price, offer, "direct")
                return result

        # Fallback: regex price extraction from raw HTML
        prices = re.findall(r'₹\s*([\d,]+(?:\.\d+)?)', html)
        if prices:
            price = _clean_price(prices[0])
            mrp   = price * 1.1
            disc  = _discount(price, mrp)
            result = {
                "store": store, "item": item["name"],
                "quantity": item["quantity"], "unit": item["unit"],
                "price": price, "mrp": mrp, "discount_percent": disc,
                "deal": f"{disc}% off" if disc >= 10 else None,
                "available": True,
                "delivery_time": DELIVERY_TIMES[store],
                "product_name": None,
                "source": "direct_bigbasket_regex",
            }
            _log(store, item["name"], price, None, "regex")
            return result

        print(f"  [BigBasket] Could not parse prices → LLM fallback")
        return _llm_fallback(store, item)

    except Exception as e:
        print(f"  [BigBasket] {e} → LLM fallback")
        return _llm_fallback(store, item)


# ──────────────────────────────────────────────────────────
# 4. Amazon Fresh  (direct HTTP)
# ──────────────────────────────────────────────────────────

def _scrape_amazon_fresh(item: dict) -> dict:
    store = "Amazon Fresh"
    try:
        # Amazon Fresh India node: 6444520031
        url = "https://www.amazon.in/s"
        params = {
            "k": item["name"],
            "rh": "n:6444520031",
            "dc": "",
        }
        headers = {
            **_HTTP_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        proxy = _AMZN_PROXY if _AMZN_PROXY else None
        with httpx.Client(timeout=25, follow_redirects=True, proxy=proxy, trust_env=False) as client:
            resp = client.get(url, params=params, headers=headers)

        if resp.status_code == 403:
            print(f"  [Amazon Fresh] 403 blocked (set AMZN_PROXY for real data) → LLM fallback")
            return _llm_fallback(store, item)

        html = resp.text

        # Extract price from search results: "wholePriceString":"₹299"
        price_matches = re.findall(r'"wholePriceString"\s*:\s*"₹([\d,]+)"', html)
        if not price_matches:
            # Alternate: class a-price-whole
            price_matches = re.findall(r'class="a-price-whole"[^>]*>([\d,]+)', html)

        mrp_matches = re.findall(
            r'class="a-text-price"[^>]*>\s*<span[^>]*>₹([\d,]+)', html
        )

        name_matches = re.findall(
            r'"productTitle"\s*:\s*"([^"]{10,100})"', html
        )

        if not price_matches:
            print(f"  [Amazon Fresh] No prices in HTML → LLM fallback")
            return _llm_fallback(store, item)

        price = _clean_price(price_matches[0])
        mrp   = _clean_price(mrp_matches[0]) if mrp_matches else (price * 1.1 if price else None)
        disc  = _discount(price, mrp)

        # Check for coupon
        coupon = re.search(r'Save ₹([\d,]+) with coupon', html)
        deal = f"Coupon: Save ₹{coupon.group(1)}" if coupon else (f"{disc}% off" if disc >= 10 else None)

        result = {
            "store": store, "item": item["name"],
            "quantity": item["quantity"], "unit": item["unit"],
            "price": price, "mrp": mrp, "discount_percent": disc,
            "deal": deal, "available": True,
            "delivery_time": DELIVERY_TIMES[store],
            "product_name": name_matches[0].strip() if name_matches else None,
            "source": "direct_amazon",
        }
        _log(store, item["name"], price, deal, "direct")
        return result

    except Exception as e:
        print(f"  [Amazon Fresh] {e} → LLM fallback")
        return _llm_fallback(store, item)


# ──────────────────────────────────────────────────────────
# Public pipeline API
# ──────────────────────────────────────────────────────────

_SCRAPERS: dict[str, callable] = {
    "Blinkit":      _scrape_blinkit,
    "Zepto":        _scrape_zepto,
    "BigBasket":    _scrape_bigbasket,
    "Amazon Fresh": _scrape_amazon_fresh,
}


async def scrape_store(store: str, item: dict) -> dict:
    """Run the store's scraper in a thread-pool executor (all scrapers are blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _SCRAPERS[store], item)


async def scrape_item_across_stores(item: dict) -> dict:
    """Scrape all four stores for a single item, concurrently."""
    print(f"\n  🔍 {item['quantity']} {item['unit']}  {item['name']}")
    results = await asyncio.gather(*[scrape_store(s, item) for s in STORE_NAMES])
    return {"item": item, "store_prices": list(results)}


async def scrape_all_stores(items: list[dict]) -> list[dict]:
    """Full scrape: items one-by-one, each item's stores scraped in parallel."""
    return [await scrape_item_across_stores(item) for item in items]