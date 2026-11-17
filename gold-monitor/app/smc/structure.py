"""Market Structure & Order Flow Analysis (SMC) - High Performance."""
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple

def find_swings(df: pd.DataFrame, window: int = 2) -> List[Dict[str, Any]]:
    """
    Identifies fractal swing highs and swing lows using fast NumPy arrays.
    """
    swings = []
    if df is None or len(df) < (window * 2 + 1):
        return swings

    n = len(df)
    highs = df["high"].values
    lows = df["low"].values
    dts = df["datetime"].values

    for i in range(window, n - window):
        curr_high = highs[i]
        curr_low = lows[i]

        # Swing High check
        is_high = True
        for offset in range(-window, window + 1):
            if offset != 0 and highs[i + offset] >= curr_high:
                is_high = False
                break
        if is_high:
            swings.append({
                "type": "HIGH",
                "index": i,
                "price": float(curr_high),
                "datetime": str(dts[i])
            })

        # Swing Low check
        is_low = True
        for offset in range(-window, window + 1):
            if offset != 0 and lows[i + offset] <= curr_low:
                is_low = False
                break
        if is_low:
            swings.append({
                "type": "LOW",
                "index": i,
                "price": float(curr_low),
                "datetime": str(dts[i])
            })

    swings.sort(key=lambda s: s["index"])
    return swings

def analyze_order_flow(df: pd.DataFrame, window: int = 2) -> Dict[str, Any]:
    if df is None or len(df) < 15:
        return {
            "trend": "NEUTRAL",
            "reasons": ["Insufficient data (< 15 bars)"],
            "last_swing_high": None,
            "last_swing_low": None,
            "ema_50": None,
            "ema_200": None,
            "bos": None
        }

    close = df["close"]
    span_len = min(len(df), 50)
    ema_50 = float(close.ewm(span=span_len, adjust=False).mean().iloc[-1])
    ema_200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(df) >= 200 else None

    swings = find_swings(df, window=window)
    highs = [s for s in swings if s["type"] == "HIGH"]
    lows = [s for s in swings if s["type"] == "LOW"]

    last_high = highs[-1] if highs else None
    last_low = lows[-1] if lows else None
    prev_high = highs[-2] if len(highs) >= 2 else None
    prev_low = lows[-2] if len(lows) >= 2 else None

    curr_close = float(close.iloc[-1])

    bullish_structure = False
    bearish_structure = False

    if last_high and prev_high and last_low and prev_low:
        if last_high["price"] > prev_high["price"] and last_low["price"] > prev_low["price"]:
            bullish_structure = True
        elif last_high["price"] < prev_high["price"] and last_low["price"] < prev_low["price"]:
            bearish_structure = True

    bos = None
    if last_high and curr_close > last_high["price"]:
        bos = "BULLISH_BOS"
    elif last_low and curr_close < last_low["price"]:
        bos = "BEARISH_BOS"

    trend = "NEUTRAL"
    reasons = []

    if curr_close > ema_50 and (ema_200 is None or curr_close > ema_200) and (bullish_structure or bos == "BULLISH_BOS"):
        trend = "BULLISH"
        reasons.append("Price above EMA50 and printing Higher Highs/Higher Lows or Bullish BOS")
    elif curr_close < ema_50 and (ema_200 is None or curr_close < ema_200) and (bearish_structure or bos == "BEARISH_BOS"):
        trend = "BEARISH"
        reasons.append("Price below EMA50 and printing Lower Highs/Lower Lows or Bearish BOS")
    elif curr_close > ema_50:
        trend = "BULLISH"
        reasons.append("Price above EMA50, holding bullish bias")
    elif curr_close < ema_50:
        trend = "BEARISH"
        reasons.append("Price below EMA50, holding bearish bias")
    else:
        trend = "NEUTRAL"
        reasons.append("Price consolidating around moving averages")

    return {
        "trend": trend,
        "reasons": reasons,
        "last_swing_high": last_high["price"] if last_high else None,
        "last_swing_low": last_low["price"] if last_low else None,
        "recent_highs": [h["price"] for h in highs[-3:]],
        "recent_lows": [l["price"] for l in lows[-3:]],
        "ema_50": ema_50,
        "ema_200": ema_200,
        "bos": bos,
        "current_price": curr_close
    }
