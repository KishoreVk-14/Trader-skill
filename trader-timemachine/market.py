#!/usr/bin/env python3
"""Market Profiles and multi-market helper for day-trader-skill.
Supports US Equities, Indian Equities (NSE/BSE), Crypto (24/7), and Forex (24/5).
Standard library only.
"""

import datetime
import re

MARKET_US = "us"
MARKET_INDIA = "india"
MARKET_CRYPTO = "crypto"
MARKET_FOREX = "forex"

NSE_HOLIDAYS_2026_2027 = {
    # 2026 NSE Trading Holidays (Sample standard Indian national & market holidays)
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-20": "Id-Ul-Fitr (Ramzan Id)",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-08-15": "Independence Day",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-08": "Diwali Laxmi Pujan",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Gurunanak Jayanti",
    "2026-12-25": "Christmas Day",
    # 2027
    "2027-01-26": "Republic Day",
    "2027-03-22": "Holi",
    "2027-03-26": "Good Friday",
    "2027-04-14": "Ambedkar Jayanti",
    "2027-08-15": "Independence Day",
    "2027-10-02": "Gandhi Jayanti",
    "2027-10-29": "Diwali",
    "2027-12-25": "Christmas Day",
}

MARKET_SPECS = {
    MARKET_US: {
        "name": "US Equities (NYSE / NASDAQ)",
        "currency": "USD",
        "symbol": "$",
        "tz_name": "America/New_York",
        "tz_offset_hours": -5,   # Base Eastern Time (EST)
        "has_dst": True,
        "open_time": datetime.time(9, 30),
        "close_time": datetime.time(16, 0),
        "flat_by": datetime.time(15, 55),
        "or_minutes": 15,
        "fractional": False,
        "is_24_7": False,
        "is_24_5": False,
        "broker_default": "alpaca"
    },
    MARKET_INDIA: {
        "name": "Indian Equities (NSE / BSE)",
        "currency": "INR",
        "symbol": "\u20b9",     # ₹
        "tz_name": "Asia/Kolkata",
        "tz_offset_hours": 5.5,  # IST is UTC+5:30 year-round (no DST)
        "has_dst": False,
        "open_time": datetime.time(9, 15),
        "close_time": datetime.time(15, 30),
        "flat_by": datetime.time(15, 15),
        "or_minutes": 15,
        "fractional": False,
        "is_24_7": False,
        "is_24_5": False,
        "broker_default": "zerodha"
    },
    MARKET_CRYPTO: {
        "name": "Crypto (24/7 Spot / Perpetuals)",
        "currency": "USD",
        "symbol": "$",
        "tz_name": "UTC",
        "tz_offset_hours": 0.0,
        "has_dst": False,
        "open_time": datetime.time(0, 0),
        "close_time": datetime.time(23, 59, 59),
        "flat_by": datetime.time(23, 55),
        "or_minutes": 30,
        "fractional": True,
        "is_24_7": True,
        "is_24_5": False,
        "broker_default": "binance"
    },
    MARKET_FOREX: {
        "name": "Forex (24/5 Interbank FX)",
        "currency": "USD",
        "symbol": "$",
        "tz_name": "UTC",
        "tz_offset_hours": 0.0,
        "has_dst": False,
        "open_time": datetime.time(8, 0),    # London Open (08:00 UTC) default session
        "close_time": datetime.time(21, 0),  # NY Session Close
        "flat_by": datetime.time(20, 55),
        "or_minutes": 15,
        "fractional": True,
        "is_24_7": False,
        "is_24_5": True,
        "broker_default": "oanda"
    }
}

# Recognized ticker patterns
INDIAN_TICKER_RE = re.compile(r"^[A-Z0-9&-]+(\.(NS|BO))$", re.IGNORECASE)
FOREX_TICKER_RE = re.compile(r"^([A-Z]{6}=X|[A-Z]{3}/[A-Z]{3}|[A-Z]{6})$", re.IGNORECASE)
CRYPTO_TICKER_RE = re.compile(r"^([A-Z0-9]+-(USD|USDT|EUR|GBP|BTC|ETH)|BTC|ETH|SOL|DOGE|XRP)$", re.IGNORECASE)
US_TICKER_RE = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$")


def detect_market(symbol):
    """Detect the market category from symbol name."""
    s = (symbol or "").strip().upper()
    if INDIAN_TICKER_RE.match(s):
        return MARKET_INDIA
    if s.endswith("=X") or "/" in s or FOREX_TICKER_RE.match(s):
        return MARKET_FOREX
    if "-" in s or s in ("BTC", "ETH", "SOL", "DOGE", "XRP", "BNB", "ADA") or CRYPTO_TICKER_RE.match(s):
        return MARKET_CRYPTO
    return MARKET_US


def get_market_spec(market_or_symbol):
    """Return the market specification dict."""
    if market_or_symbol in MARKET_SPECS:
        m = market_or_symbol
    else:
        m = detect_market(market_or_symbol)
    return MARKET_SPECS[m]


def normalize_yahoo_symbol(symbol):
    """Format symbol for Yahoo Finance query.
    Keeps .NS, .BO, =X intact; converts US dot shares (BRK.B) to BRK-B.
    """
    s = (symbol or "").strip().upper()
    if s.endswith((".NS", ".BO", "=X")):
        return s
    if "/" in s and len(s) == 7: # EUR/USD -> EURUSD=X
        return s.replace("/", "") + "=X"
    if s in ("BTC", "ETH", "SOL", "DOGE", "XRP", "BNB", "ADA"):
        return f"{s}-USD"
    # US class share conversion: BRK.B -> BRK-B
    return s.replace(".", "-")


def is_market_open(market, dt_utc=None):
    """Check if the given market is currently open at dt_utc."""
    if dt_utc is None:
        dt_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    
    spec = MARKET_SPECS.get(market, MARKET_SPECS[MARKET_US])
    if spec["is_24_7"]:
        return True, "Crypto market is open 24/7"
    
    weekday = dt_utc.weekday() # 0 = Monday, 6 = Sunday
    if spec["is_24_5"]: # Forex: opens Sun 21:00 UTC, closes Fri 21:00 UTC
        if weekday == 5: # Saturday
            return False, "Forex closed on Saturday"
        if weekday == 6 and dt_utc.time() < datetime.time(21, 0):
            return False, "Forex opens Sunday 21:00 UTC"
        if weekday == 4 and dt_utc.time() >= datetime.time(21, 0):
            return False, "Forex closes Friday 21:00 UTC"
        return True, "Forex market is open"
        
    if market == MARKET_INDIA:
        if weekday >= 5:
            return False, "Indian market closed on weekend"
        # Local IST time
        local_dt = dt_utc + datetime.timedelta(hours=5.5)
        d_str = local_dt.date().isoformat()
        if d_str in NSE_HOLIDAYS_2026_2027:
            return False, f"NSE Holiday: {NSE_HOLIDAYS_2026_2027[d_str]}"
        t = local_dt.time()
        if spec["open_time"] <= t <= spec["close_time"]:
            return True, f"NSE / BSE is open ({t.strftime('%H:%M')} IST)"
        return False, f"NSE / BSE is closed ({t.strftime('%H:%M')} IST; session 09:15 to 15:30)"

    # US Market check fallback
    if weekday >= 5:
        return False, "US market closed on weekend"
    # Approximate US Eastern
    local_dt = dt_utc - datetime.timedelta(hours=5)
    t = local_dt.time()
    if spec["open_time"] <= t <= spec["close_time"]:
        return True, f"US market is open ({t.strftime('%H:%M')} ET)"
    return False, f"US market is closed ({t.strftime('%H:%M')} ET; session 09:30 to 16:00)"
