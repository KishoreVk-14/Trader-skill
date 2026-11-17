"""Institutional Order Block (OB) Detection Engine for 15M, 30M, 1H, and 4H timeframes."""
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional

def find_order_blocks(
    df: pd.DataFrame,
    lookback: int = 50,
    min_displacement_atr_mult: float = 1.2
) -> List[Dict[str, Any]]:
    """
    Scans for institutional Order Blocks:
    - Bullish OB: The last down-close (bearish) candle before a strong upward displacement breaking structure.
    - Bearish OB: The last up-close (bullish) candle before a strong downward displacement breaking structure.
    """
    if df is None or len(df) < 5:
        return []

    # Use raw numpy arrays for performance
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    datetimes = df["datetime"].values
    n = len(df)

    start_idx = max(2, n - lookback)
    order_blocks = []

    for i in range(start_idx, n - 1):
        prev_o = opens[i - 1]
        prev_c = closes[i - 1]
        prev_h = highs[i - 1]
        prev_l = lows[i - 1]

        curr_o = opens[i]
        curr_c = closes[i]
        curr_h = highs[i]
        curr_l = lows[i]

        # Candle i+1 (expansion confirmation if available)
        next_c = closes[i + 1] if i + 1 < n else curr_c

        # 1. Bullish Order Block Check
        # Candle i-1 was bearish (prev_c < prev_o)
        # Candle i & i+1 show strong impulsive bullish displacement breaking prev_h
        if prev_c < prev_o and curr_c > prev_h:
            displacement = curr_c - prev_o
            candle_body = abs(prev_c - prev_o)
            # Ensure significant displacement
            if displacement > candle_body * 0.8:
                ob = {
                    "type": "BULLISH_OB",
                    "index": i - 1,
                    "datetime": str(datetimes[i - 1]),
                    "top": round(float(prev_h), 2),
                    "bottom": round(float(prev_l), 2),
                    "body_top": round(float(prev_o), 2),
                    "body_bottom": round(float(prev_c), 2),
                    "mitigated": False
                }
                # Check if subsequent candles mitigated this OB
                for k in range(i + 1, n):
                    if lows[k] <= ob["top"] and closes[k] >= ob["bottom"]:
                        ob["mitigated"] = True
                        ob["mitigated_at"] = str(datetimes[k])
                        break
                    elif closes[k] < ob["bottom"]:
                        # Invalidated / broken OB
                        ob["mitigated"] = False
                        break
                order_blocks.append(ob)

        # 2. Bearish Order Block Check
        # Candle i-1 was bullish (prev_c > prev_o)
        # Candle i & i+1 show strong impulsive bearish displacement breaking prev_l
        elif prev_c > prev_o and curr_c < prev_l:
            displacement = prev_o - curr_c
            candle_body = abs(prev_c - prev_o)
            if displacement > candle_body * 0.8:
                ob = {
                    "type": "BEARISH_OB",
                    "index": i - 1,
                    "datetime": str(datetimes[i - 1]),
                    "top": round(float(prev_h), 2),
                    "bottom": round(float(prev_l), 2),
                    "body_top": round(float(prev_c), 2),
                    "body_bottom": round(float(prev_o), 2),
                    "mitigated": False
                }
                for k in range(i + 1, n):
                    if highs[k] >= ob["bottom"] and closes[k] <= ob["top"]:
                        ob["mitigated"] = True
                        ob["mitigated_at"] = str(datetimes[k])
                        break
                    elif closes[k] > ob["top"]:
                        ob["mitigated"] = False
                        break
                order_blocks.append(ob)

    return order_blocks

def check_order_block_mitigation(
    current_price: float,
    order_blocks: List[Dict[str, Any]],
    expected_type: str = "BULLISH_OB",
    tolerance_usd: float = 1.50
) -> Dict[str, Any]:
    """
    Checks if current price is inside or actively respecting a valid Order Block of the expected type.
    """
    for ob in reversed(order_blocks):
        if ob["type"] == expected_type:
            # Check if price is within OB zone with small tolerance
            if (ob["bottom"] - tolerance_usd) <= current_price <= (ob["top"] + tolerance_usd):
                return {
                    "confirmed": True,
                    "ob": ob,
                    "detail": f"Mitigating {expected_type} [{ob['bottom']} - {ob['top']}] from {ob['datetime']}"
                }
    return {
        "confirmed": False,
        "ob": None,
        "detail": f"No active {expected_type} confluence at ${current_price:.2f}"
    }
