#!/usr/bin/env python3
"""
Stock Alert Script
- SPCX, GLD, TSLA: alert on ±5% daily move  OR  3 consecutive up/down days
- S&P 500 (^GSPC):  alert after 3 consecutive down days
"""

import sys
import json
import time
from datetime import datetime
from typing import Optional, List, Tuple
import urllib.request
import urllib.error

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "8956424241:AAEGRHwoLWlvG-ph4n2OWUcTKmJpy0UEAng"
TELEGRAM_CHAT_ID   = "8687524205"

TICKERS            = ["SPCX", "GLD", "TSLA"]
SPX_TICKER         = "^GSPC"
THRESHOLD          = 5.0          # percent for ±5% same-day move
STREAK_REQUIRED     = 3           # consecutive up/down days before alerting a stock
SPX_STREAK_DOWNS   = 3           # consecutive down days before alerting S&P 500

CACHE_FILE         = "/home/jlam/.openclaw/workspace/.stock_cache.json"
# ─────────────────────────────────────────────────────────────────────────────

def get_telegram_safe_mode():
    import os
    return os.environ.get("OPENCLAW_SAFE_EXEC", "").lower() != "false"


def fetch_quote(ticker: str) -> Optional[dict]:
    """Fetch price + previous close from Yahoo Finance. Returns None on failure."""
    time.sleep(1.5)

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&range=10d"
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

        prev_close = meta.get("previousClose")
        if not prev_close:
            try:
                closes = result["indicators"]["quote"][0]["close"]
                closes = [c for c in closes if c is not None]
                if len(closes) >= 2:
                    prev_close = closes[-2]
                elif len(closes) == 1:
                    prev_close = closes[0]
            except (KeyError, IndexError):
                pass

        if price is None or prev_close is None or prev_close == 0:
            print(f"[WARN] Could not determine price/prev_close for {ticker}", file=sys.stderr)
            return None

        change_pct = ((price - prev_close) / prev_close) * 100
        return {
            "price":      round(price, 4),
            "prev_close": round(prev_close, 4),
            "change_pct": round(change_pct, 2),
        }

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
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}).encode()
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}", file=sys.stderr)
        return False


# ── History helpers ────────────────────────────────────────────────────────────

def build_history(ticker: str, cache: dict, max_days: int = 10) -> List[dict]:
    """
    Append today's quote to the cached rolling history for `ticker`.
    Returns the updated list (most recent last).
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    history   = list(cache.get(f"{ticker}_history", []))

    q = fetch_quote(ticker)
    if q is None:
        return history

    record = {
        "date":       today_str,
        "close":      q["price"],
        "prev_close": q["prev_close"],
        "change_pct": q["change_pct"],
    }

    if history and history[-1]["date"] == today_str:
        history[-1] = record          # refresh today's entry
    else:
        history.append(record)

    history = history[-max_days:]

    cache[f"{ticker}_history"] = history
    cache[ticker] = {
        "price":      q["price"],
        "prev_close": q["prev_close"],
        "date":       today_str,
    }

    return history


def check_streak(history: List[dict], required: int, direction: str) -> Tuple[bool, List[dict]]:
    """
    Return (triggered, streak_records) where the streak is `required` consecutive
    days all going the same direction.
    direction: 'up'   → all change_pct > 0
               'down' → all change_pct < 0
    Returns (False, []) if history is shorter than `required`.
    """
    if len(history) < required:
        return False, []

    recent = history[-required:]
    if direction == "up":
        triggered = all(r["change_pct"] > 0 for r in recent)
    else:
        triggered = all(r["change_pct"] < 0 for r in recent)

    return triggered, (list(recent) if triggered else [])


def format_5pct_alert(ticker: str, q: dict) -> str:
    emoji     = "🔴" if q["change_pct"] < 0 else "🟢"
    direction = "DOWN" if q["change_pct"] < 0 else "UP"
    return (
        f"{emoji} <b>Stock Alert: {ticker}</b>\n"
        f"   {direction} {abs(q['change_pct']):.2f}% today\n"
        f"   Price: ${q['price']:.2f} | Prev: ${q['prev_close']:.2f}"
    )


def format_streak_alert(ticker: str, direction: str, records: List[dict]) -> str:
    """
    Format a consecutive-day streak alert.
    direction: 'up' or 'down'
    """
    emoji     = "🟢" if direction == "up" else "🔴"
    adj       = "gaining" if direction == "up" else "losing"
    sign      = "+" if direction == "up" else "-"
    streak_pct = ", ".join(f"{sign}{abs(r['change_pct']):.2f}%" for r in records)
    total_chg = sum(r["change_pct"] for r in records)
    start_p   = records[0]["prev_close"]
    end_p     = records[-1]["close"]
    streak_str = f"{streak_pct} ({sign}{abs(total_chg):.2f}% cumulative, ${start_p:.2f} → ${end_p:.2f})"

    return (
        f"{emoji} <b>{ticker} Alert: {len(records)} Consecutive {direction.upper()} Days</b>\n"
        f"   {emoji.replace('🔴','📉').replace('🟢','📈')} {adj.capitalize()} for {len(records)} straight days: {streak_str}"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now().isoformat()}] Stock alert check starting...")

    today_str = datetime.now().strftime("%Y-%m-%d")
    cache     = load_cache()
    alerts_5pct    = []
    alert_streaks  = []    # list of (ticker, direction, records)
    alert_spx_down = None

    # ── 5% same-day alerts + build rolling history for all stocks ──────────
    for ticker in TICKERS:
        q = fetch_quote(ticker)
        if q is None:
            print(f"  {ticker}: fetch failed -- skipping")
            continue

        print(f"  {ticker}: price=${q['price']:.2f}, prev=${q['prev_close']:.2f}, chg={q['change_pct']:+.2f}%")

        # 5% threshold check
        if abs(q["change_pct"]) >= THRESHOLD:
            alerts_5pct.append((ticker, q))

        # Build / update rolling history for streak detection
        history = build_history(ticker, cache)

        # Check consecutive UP streak
        triggered_up, up_records = check_streak(history, STREAK_REQUIRED, "up")
        if triggered_up:
            alert_streaks.append((ticker, "up", up_records))
            print(f"    *** {ticker}: {STREAK_REQUIRED} consecutive UP days TRIGGERED")

        # Check consecutive DOWN streak
        triggered_down, down_records = check_streak(history, STREAK_REQUIRED, "down")
        if triggered_down:
            alert_streaks.append((ticker, "down", down_records))
            print(f"    *** {ticker}: {STREAK_REQUIRED} consecutive DOWN days TRIGGERED")

        if not triggered_up and not triggered_down:
            recent = history[-STREAK_REQUIRED:] if len(history) >= STREAK_REQUIRED else history
            signs  = " ".join(f"{'+' if r['change_pct'] > 0 else ''}{r['change_pct']:+.2f}%" for r in recent)
            print(f"    Streak status: {len(recent)}/{STREAK_REQUIRED} tracked ({signs})")

    # ── S&P 500 3 consecutive down days ─────────────────────────────────────
    print(f"\n  Building SPX history...")
    spx_history = build_history(SPX_TICKER, cache)

    for r in spx_history:
        print(f"    {r['date']}: {r['change_pct']:+.2f}%")

    spx_triggered, spx_records = check_streak(spx_history, SPX_STREAK_DOWNS, "down")
    if spx_triggered:
        alert_spx_down = list(spx_records)
        print(f"\n  SPX: {SPX_STREAK_DOWNS} consecutive DOWN days TRIGGERED")
    else:
        print(f"\n  SPX: {len(spx_history)} days tracked, no alert (need {SPX_STREAK_DOWNS} consecutive down)")

    # Always persist cache at the end
    save_cache(cache)

    # ── Build & send Telegram message ──────────────────────────────────────
    all_lines = []

    if alerts_5pct:
        all_lines.append(f"<b>Stock Alert -- {today_str}</b> (threshold: ±{THRESHOLD}%)\n")
        all_lines += [format_5pct_alert(t, q) for t, q in alerts_5pct]
        all_lines.append("")

    if alert_streaks:
        all_lines.append(f"<b>Streak Alert -- {STREAK_REQUIRED} Consecutive Days</b>\n")
        for ticker, direction, records in alert_streaks:
            all_lines.append(format_streak_alert(ticker, direction, records))
        all_lines.append("")

    if alert_spx_down is not None:
        streak     = alert_spx_down
        total_chg  = sum(r["change_pct"] for r in streak)
        first_p    = streak[0]["prev_close"]
        last_p     = streak[-1]["close"]
        streak_str = ", ".join(f"{r['change_pct']:+.2f}%" for r in streak)
        all_lines.append(
            f"<b>S&amp;P 500 Alert -- {SPX_STREAK_DOWNS} Consecutive Down Days</b>\n"
            f"   🔴 {SPX_STREAK_DOWNS} straight down days: {streak_str}\n"
            f"   Cumulative drop: {total_chg:.2f}% (${first_p:.2f} → ${last_p:.2f})"
        )
        all_lines.append("")

    if all_lines:
        message = "\n".join(all_lines).strip()

        if get_telegram_safe_mode():
            print("\n[TG DEMO -- safe-exec blocked send]")
            print(message)
        else:
            ok = send_telegram(message)
            print(f"\n  Telegram sent: {'OK' if ok else 'FAILED'}")
    else:
        print("\n  No alerts triggered.")


if __name__ == "__main__":
    main()
