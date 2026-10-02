#!/usr/bin/env python3
"""
Stock Alert Script - monitors SPACX, GLD, TSLA for 5%+ daily moves.
Sends alerts via Telegram when threshold is crossed.
"""

import sys
import json
import time
from datetime import datetime
from typing import Optional
import urllib.request
import urllib.error

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "8956424241:AAEGRHwoLWlvG-ph4n2OWUcTKmJpy0UEAng"   # Set your Telegram bot token
TELEGRAM_CHAT_ID   = "8687524205"       # Your Telegram chat ID
TICKERS            = ["SPCX", "GLD", "TSLA"]
THRESHOLD          = 5.0                # percent
CACHE_FILE         = "/home/jlam/.openclaw/workspace/.stock_cache.json"
# ─────────────────────────────────────────────────────────────────────────────

def get_telegram_safe_mode():
    """Detect if we're in a safe execution context for sending messages."""
    import os
    return os.environ.get("OPENCLAW_SAFE_EXEC", "").lower() != "false"

def fetch_quote(ticker: str) -> Optional[dict]:
    """
    Fetch current price and previous close for `ticker` using Yahoo Finance.
    Returns dict with `price`, `prev_close`, `change_pct`, or None on failure.
    """
    time.sleep(1.5)   # avoid rate-limit bursts between tickers

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&range=5d"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        result = data["chart"]["result"]
        if not result or result is None:
            print(f"[WARN] No data for {ticker} -- symbol may be delisted/unknown", file=sys.stderr)
            return None

        result = result[0]
        meta   = result["meta"]
        price  = meta.get("regularMarketPrice") or meta.get("previousClose")

        # previousClose may be absent; derive from closes array
        prev_close = meta.get("previousClose")
        if not prev_close:
            try:
                closes = result["indicators"]["quote"][0]["close"]
                closes = [c for c in closes if c is not None]   # filter None
                if len(closes) >= 2:
                    prev_close = closes[-2]   # second-to-last = previous close
                elif len(closes) == 1:
                    prev_close = closes[0]
            except (KeyError, IndexError):
                pass

        if price is None or prev_close is None or prev_close == 0:
            print(f"[WARN] Could not determine price/prev_close for {ticker}", file=sys.stderr)
            return None

        change_pct = ((price - prev_close) / prev_close) * 100
        return {"price": round(price, 4), "prev_close": round(prev_close, 4), "change_pct": round(change_pct, 2)}

    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"[WARN] Rate-limited for {ticker} (429); will retry next run", file=sys.stderr)
        else:
            print(f"[WARN] HTTP error for {ticker}: {e.code} {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] Failed to fetch {ticker}: {e}", file=sys.stderr)
        return None


def load_cache() -> dict:
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def send_telegram(message: str) -> bool:
    """Send a message via Telegram bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}).encode()
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}", file=sys.stderr)
        return False


def format_alert(ticker: str, q: dict) -> str:
    emoji     = "🔴" if q["change_pct"] < 0 else "🟢"
    direction = "DOWN" if q["change_pct"] < 0 else "UP"
    return (
        f"{emoji} <b>Stock Alert: {ticker}</b>\n"
        f"   {direction} {abs(q['change_pct']):.2f}% today\n"
        f"   Price: ${q['price']:.2f} | Prev: ${q['prev_close']:.2f}"
    )


def main():
    print(f"[{datetime.now().isoformat()}] Stock alert check starting...")

    today_str = datetime.now().strftime("%Y-%m-%d")
    cache     = load_cache()
    alerts    = []

    for ticker in TICKERS:
        q = fetch_quote(ticker)
        if q is None:
            print(f"  {ticker}: fetch failed -- skipping")
            continue

        print(f"  {ticker}: price=${q['price']:.2f}, prev=${q['prev_close']:.2f}, chg={q['change_pct']:+.2f}%")

        # Always cache today's data for next-run comparison baseline
        cache[ticker] = {
            "price":      q["price"],
            "prev_close": q["prev_close"],
            "date":       today_str,
        }

        abs_chg = abs(q["change_pct"])
        if abs_chg >= THRESHOLD:
            alerts.append((ticker, q))

    # Persist cache
    save_cache(cache)

    # Build & send Telegram message
    if alerts:
        lines = [f"Stock Alert -- {today_str}\n(threshold: ±{THRESHOLD}%)\n"]
        lines += [format_alert(t, q) for t, q in alerts]
        message = "\n".join(lines)

        if "YOUR_BOT_TOKEN" in TELEGRAM_BOT_TOKEN:
            print("\n[TG DEMO -- set TELEGRAM_BOT_TOKEN to send real alerts]")
            print(message)
        elif get_telegram_safe_mode():
            print("[SKIP] Telegram send blocked in safe-exec context")
        else:
            ok = send_telegram(message)
            print(f"  Telegram sent: {'OK' if ok else 'FAILED'}")
    else:
        print("  No alerts triggered.")


if __name__ == "__main__":
    main()
