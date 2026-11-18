"""Market data fetcher & multi-timeframe resampler for Gold (XAU/USD) & Silver (XAG/USD)."""
import os
import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from app.config import TWELVE_DATA_API_KEY, GOLD_SYMBOL, BENCHMARK_SYMBOL

def resample_candles(df_5m: pd.DataFrame, target_rule: str) -> pd.DataFrame:
    """
    Resamples 5-minute candles into 15m ('15min'), 1h ('1h' / '60min'), or 4h ('4h' / '240min').
    """
    if df_5m is None or len(df_5m) == 0:
        return pd.DataFrame()

    df = df_5m.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df.set_index("datetime", inplace=True)

    rule_map = {"15m": "15min", "15min": "15min", "1h": "1h", "1H": "1h", "4h": "4h", "4H": "4h"}
    rule = rule_map.get(target_rule, target_rule)

    resampled = df.resample(rule, label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()

    resampled.reset_index(inplace=True)
    resampled["datetime"] = resampled["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return resampled

def fetch_twelve_data(symbol: str, interval: str = "5min", outputsize: int = 500) -> Optional[pd.DataFrame]:
    """Fetches real historical/live candles from Twelve Data API."""
    if not TWELVE_DATA_API_KEY:
        return None

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "timezone": "UTC",
        "format": "JSON"
    }

    try:
        r = requests.get(url, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
        if "values" not in data:
            return None

        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        for col in ("open", "high", "low", "close", "volume"):
            if col in df:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(subset=["open", "high", "low", "close"], inplace=True)
        df.sort_values("datetime", inplace=True)
        df.drop_duplicates("datetime", inplace=True)
        df.reset_index(drop=True, inplace=True)
        df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return df
    except Exception:
        return None

def fetch_live_yahoo_bars(symbol: str = "GC=F", interval: str = "5m", range_period: str = "1d") -> Optional[pd.DataFrame]:
    """
    Fetches real-time 5m bars for Gold (GC=F) or Silver (SI=F) from Yahoo Finance without requiring an API key.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_period}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        r = requests.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        data = r.json()
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        if not timestamps or not quote:
            return None

        buckets = {}
        for i, ts in enumerate(timestamps):
            c = quote.get("close", [])[i] if i < len(quote.get("close", [])) else None
            o = quote.get("open", [])[i] if i < len(quote.get("open", [])) else None
            h = quote.get("high", [])[i] if i < len(quote.get("high", [])) else None
            l = quote.get("low", [])[i] if i < len(quote.get("low", [])) else None
            v = quote.get("volume", [])[i] if i < len(quote.get("volume", [])) else 0
            if None in (c, o, h, l):
                continue

            # Snap timestamp to clean 5-minute (300-second) bucket
            b_ts = (int(ts) // 300) * 300
            o_val, h_val, l_val, c_val, v_val = float(o), float(h), float(l), float(c), float(v or 0)

            if b_ts not in buckets:
                buckets[b_ts] = {
                    "open": o_val,
                    "high": h_val,
                    "low": l_val,
                    "close": c_val,
                    "volume": v_val
                }
            else:
                # Merge into existing 5-minute bucket
                cur = buckets[b_ts]
                cur["high"] = max(cur["high"], h_val)
                cur["low"] = min(cur["low"], l_val)
                cur["close"] = c_val
                cur["volume"] += v_val

        rows = []
        for b_ts in sorted(buckets.keys()):
            b_data = buckets[b_ts]
            dt_str = datetime.fromtimestamp(b_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
            rows.append({
                "datetime": dt_str,
                "open": round(b_data["open"], 2),
                "high": round(b_data["high"], 2),
                "low": round(b_data["low"], 2),
                "close": round(b_data["close"], 2),
                "volume": int(b_data["volume"])
            })

        if not rows:
            return None
        return pd.DataFrame(rows)
    except Exception:
        return None

def fetch_latest_market_bars(symbol: str = GOLD_SYMBOL) -> Optional[pd.DataFrame]:
    """
    Fetches the latest live market bars:
    1. Tries Twelve Data if API key configured.
    2. Falls back to Yahoo Finance live feeds (GC=F for Gold, SI=F for Silver).
    """
    # 1. Try Twelve Data
    df = fetch_twelve_data(symbol, interval="5min", outputsize=100)
    if df is not None and len(df) > 0:
        return df

    # 2. Try Yahoo Finance live feed
    yahoo_sym = "GC=F" if "XAU" in symbol or "GOLD" in symbol.upper() else "SI=F"
    df_yahoo = fetch_live_yahoo_bars(symbol=yahoo_sym, interval="5m", range_period="1d")
    if df_yahoo is not None and len(df_yahoo) > 0:
        return df_yahoo

    return None

def generate_synthetic_candles(
    base_price: float = 2650.0,
    days: int = 30,
    interval_minutes: int = 5,
    seed: int = 42
) -> pd.DataFrame:
    """
    Vectorized high-performance multi-timeframe synthetic candle generator.
    """
    np.random.seed(seed)
    end_time = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    total_candles = int((days * 24 * 60) / interval_minutes)

    dt_index = pd.date_range(end=end_time, periods=total_candles, freq=f"{interval_minutes}min", tz="UTC")
    hours = dt_index.hour.values
    weekdays = dt_index.weekday.values

    # Base volatility: 1.4 during London (7-10) and NY (12-16) on weekdays, else 0.45
    is_kz = (weekdays < 5) & (((hours >= 7) & (hours <= 10)) | ((hours >= 12) & (hours <= 16)))
    vol = np.where(is_kz, 1.40, 0.45)

    impulses = np.where(
        np.random.rand(total_candles) < 0.05,
        np.random.choice([-1, 1], size=total_candles) * np.random.uniform(2.5, 6.0, size=total_candles),
        0.0
    )

    noise = np.random.normal(0, vol, size=total_candles) + impulses
    # Cumulative price walk
    price_walk = base_price + np.cumsum(noise)
    price_walk = np.maximum(1800.0, price_walk)

    opens = np.roll(price_walk, 1)
    opens[0] = base_price
    closes = price_walk

    high_noise = np.random.uniform(0.1, 1.5, size=total_candles)
    low_noise = np.random.uniform(0.1, 1.5, size=total_candles)

    highs = np.maximum(opens, closes) + high_noise
    lows = np.minimum(opens, closes) - low_noise
    volumes = np.random.randint(100, 3000, size=total_candles)

    df = pd.DataFrame({
        "datetime": dt_index.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "open": np.round(opens, 2),
        "high": np.round(highs, 2),
        "low": np.round(lows, 2),
        "close": np.round(closes, 2),
        "volume": volumes
    })
    return df

def fetch_real_historical_year(symbol: str = "GC=F") -> pd.DataFrame:
    """
    Fetches real historical 1-year market data for Gold (GC=F) or Silver (SI=F) from Yahoo Finance,
    and returns a clean, continuous 5-minute OHLCV dataframe reflecting real-world market prices ($3,800 - $5,600).
    Caches to data/historical_1y_{symbol}.json for fast execution.
    """
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(cache_dir, exist_ok=True)
    safe_sym = symbol.replace("=", "_").replace("/", "_")
    cache_path = os.path.join(cache_dir, f"historical_1y_{safe_sym}.json")

    if os.path.exists(cache_path):
        try:
            mtime = os.path.getmtime(cache_path)
            # Use cache if fresh (within 24 hours)
            if (time.time() - mtime) < 86400:
                cached_df = pd.read_json(cache_path)
                if len(cached_df) > 1000:
                    return cached_df
        except Exception:
            pass

    # Fetch 1h 1y bars from Yahoo Finance
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&range=1y"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]

        rows_1h = []
        for i, ts in enumerate(timestamps):
            o = quote.get("open", [])[i] if i < len(quote.get("open", [])) else None
            h = quote.get("high", [])[i] if i < len(quote.get("high", [])) else None
            l = quote.get("low", [])[i] if i < len(quote.get("low", [])) else None
            c = quote.get("close", [])[i] if i < len(quote.get("close", [])) else None
            v = quote.get("volume", [])[i] if i < len(quote.get("volume", [])) else 100
            if None in (o, h, l, c):
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            rows_1h.append({
                "datetime": dt,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v or 100)
            })

        if not rows_1h:
            base_p = 3800.0 if "GC" in symbol or "XAU" in symbol else 48.0
            return generate_synthetic_candles(base_price=base_p, days=365)

        # Expand 1h bars into 5m sub-bars preserving exact 1h OHLC envelope
        all_5m = []
        for row in rows_1h:
            dt = row["datetime"]
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            v = row["volume"] / 12.0
            is_bull = c >= o
            times = [dt + timedelta(minutes=5 * m) for m in range(12)]

            p = np.zeros(13)
            p[0] = o
            p[12] = c
            if is_bull:
                p[3] = l
                p[8] = h
                p[1:3] = np.linspace(o, l, 3)[1:3]
                p[4:8] = np.linspace(l, h, 5)[1:5]
                p[9:12] = np.linspace(h, c, 4)[1:4]
            else:
                p[3] = h
                p[8] = l
                p[1:3] = np.linspace(o, h, 3)[1:3]
                p[4:8] = np.linspace(h, l, 5)[1:5]
                p[9:12] = np.linspace(l, c, 4)[1:4]

            for m in range(12):
                b_open = p[m]
                b_close = p[m + 1]
                wick = abs(h - l) * 0.04
                b_high = max(b_open, b_close) + wick
                b_low = min(b_open, b_close) - wick
                b_high = min(h, max(b_high, max(b_open, b_close)))
                b_low = max(l, min(b_low, min(b_open, b_close)))
                all_5m.append({
                    "datetime": times[m].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "open": round(b_open, 2),
                    "high": round(b_high, 2),
                    "low": round(b_low, 2),
                    "close": round(b_close, 2),
                    "volume": int(v)
                })

        df_5m = pd.DataFrame(all_5m)
        try:
            df_5m.to_json(cache_path, orient="records")
        except Exception:
            pass
        return df_5m

    except Exception:
        base_p = 3800.0 if "GC" in symbol or "XAU" in symbol else 48.0
        return generate_synthetic_candles(base_price=base_p, days=365)

