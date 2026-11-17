"""Fair Value Gap (FVG) and Consequent Encroachment (CE) Module (High Performance)."""
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional

def find_fvgs(df: pd.DataFrame, min_gap_usd: float = 0.20) -> List[Dict[str, Any]]:
    """
    Scans for 3-candle Fair Value Gaps across the dataframe using fast NumPy arrays.
    Bullish FVG: Bar(i).low > Bar(i-2).high
    Bearish FVG: Bar(i).high < Bar(i-2).low
    """
    fvgs = []
    if df is None or len(df) < 3:
        return fvgs

    n = len(df)
    highs = df["high"].values
    lows = df["low"].values
    dts = df["datetime"].values

    for i in range(2, n):
        b0_high = float(highs[i - 2])
        b0_low = float(lows[i - 2])
        b2_high = float(highs[i])
        b2_low = float(lows[i])
        b1_time = str(dts[i - 1])

        # Bullish FVG
        if b2_low > b0_high:
            gap_size = b2_low - b0_high
            if gap_size >= min_gap_usd:
                top = b2_low
                bottom = b0_high
                ce_50 = (top + bottom) / 2.0
                fvgs.append({
                    "id": f"BFVG_{i}_{b1_time}",
                    "type": "BULLISH",
                    "candle_index": i - 1,
                    "created_at": b1_time,
                    "top": round(top, 3),
                    "bottom": round(bottom, 3),
                    "ce_50": round(ce_50, 3),
                    "gap_size": round(gap_size, 3),
                    "mitigated": False,
                    "mitigated_at": None,
                    "fully_closed": False
                })

        # Bearish FVG
        elif b2_high < b0_low:
            gap_size = b0_low - b2_high
            if gap_size >= min_gap_usd:
                top = b0_low
                bottom = b2_high
                ce_50 = (top + bottom) / 2.0
                fvgs.append({
                    "id": f"BEARFVG_{i}_{b1_time}",
                    "type": "BEARISH",
                    "candle_index": i - 1,
                    "created_at": b1_time,
                    "top": round(top, 3),
                    "bottom": round(bottom, 3),
                    "ce_50": round(ce_50, 3),
                    "gap_size": round(gap_size, 3),
                    "mitigated": False,
                    "mitigated_at": None,
                    "fully_closed": False
                })

    # Fast mitigation check using NumPy arrays
    for fvg in fvgs:
        start_idx = fvg["candle_index"] + 2
        fvg_type = fvg["type"]
        fvg_top = fvg["top"]
        fvg_bottom = fvg["bottom"]

        for j in range(start_idx, n):
            c_high = float(highs[j])
            c_low = float(lows[j])

            if fvg_type == "BULLISH":
                if c_low <= fvg_top:
                    fvg["mitigated"] = True
                    if fvg["mitigated_at"] is None:
                        fvg["mitigated_at"] = str(dts[j])
                if c_low < fvg_bottom:
                    fvg["fully_closed"] = True
                    break

            elif fvg_type == "BEARISH":
                if c_high >= fvg_bottom:
                    fvg["mitigated"] = True
                    if fvg["mitigated_at"] is None:
                        fvg["mitigated_at"] = str(dts[j])
                if c_high > fvg_top:
                    fvg["fully_closed"] = True
                    break

    return fvgs

def check_htf_fvg_mitigation(curr_price: float, htf_fvgs: List[Dict[str, Any]], expected_type: str = "BULLISH") -> Optional[Dict[str, Any]]:
    matching = [f for f in htf_fvgs if f["type"] == expected_type and not f["fully_closed"]]
    matching.sort(key=lambda x: x["candle_index"], reverse=True)

    for fvg in matching:
        if fvg["type"] == "BULLISH":
            if fvg["bottom"] * 0.9995 <= curr_price <= fvg["top"] * 1.0005:
                return {
                    "is_mitigated": True,
                    "fvg": fvg,
                    "detail": f"Price ${curr_price:.2f} is currently inside {fvg['type']} FVG [{fvg['bottom']:.2f} - {fvg['top']:.2f}] (50% CE: ${fvg['ce_50']:.2f})"
                }
            elif fvg["mitigated"] and curr_price >= fvg["bottom"]:
                return {
                    "is_mitigated": True,
                    "fvg": fvg,
                    "detail": f"Price recently mitigated {fvg['type']} FVG [{fvg['bottom']:.2f} - {fvg['top']:.2f}] and is reacting"
                }

        elif fvg["type"] == "BEARISH":
            if fvg["bottom"] * 0.9995 <= curr_price <= fvg["top"] * 1.0005:
                return {
                    "is_mitigated": True,
                    "fvg": fvg,
                    "detail": f"Price ${curr_price:.2f} is currently inside {fvg['type']} FVG [{fvg['bottom']:.2f} - {fvg['top']:.2f}] (50% CE: ${fvg['ce_50']:.2f})"
                }
            elif fvg["mitigated"] and curr_price <= fvg["top"]:
                return {
                    "is_mitigated": True,
                    "fvg": fvg,
                    "detail": f"Price recently mitigated {fvg['type']} FVG [{fvg['bottom']:.2f} - {fvg['top']:.2f}] and is reacting"
                }

    return None
