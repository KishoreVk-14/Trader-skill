"""SMT (Smart Money Technique) Divergence Engine.
Compares correlated assets: Gold (XAU/USD / GC=F) vs Silver (XAG/USD / SI=F).
Strict institutional ICT SMT:
- Bullish SMT: Gold sweeps liquidity to a Lower Low (LL) while Silver holds a Higher Low (HL).
- Bearish SMT: Gold reaches a Higher High (HH) while Silver fails and forms a Lower High (LH).
No synthetic/fake fallbacks: if no divergence exists, SMT is reported as WAITING.
"""
import pandas as pd
from typing import Dict, Any, Optional
from app.smc.structure import find_swings

def detect_smt_divergence(gold_df: pd.DataFrame, silver_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    """
    Detects true SMT divergence between Gold and Silver across correlated swing points.
    Matches swings based on synchronized bar index and time window (within +-2 bars).
    """
    if gold_df is None or len(gold_df) < 10:
        return {
            "has_smt": False,
            "type": "NONE",
            "reason": "Insufficient Gold candle data for SMT analysis",
            "detail": {}
        }

    if silver_df is None or len(silver_df) < 10:
        return {
            "has_smt": False,
            "type": "NONE",
            "reason": "Silver benchmark data not available for SMT comparison",
            "detail": {}
        }

    # Find swing highs and swing lows on Gold
    gold_swings = find_swings(gold_df, window=2)
    gold_highs = [s for s in gold_swings if s["type"] == "HIGH"]
    gold_lows = [s for s in gold_swings if s["type"] == "LOW"]

    # Build synchronized Silver lookup or swings
    # If both dataframes have datetime, align by datetime or bar index
    silver_has_dt = "datetime" in silver_df.columns and "datetime" in gold_df.columns
    gold_len = len(gold_df)
    silver_len = len(silver_df)

    def get_silver_extreme_around(gold_idx: int, window: int = 2, is_high: bool = False) -> float:
        """Finds the extreme (low or high) on Silver in the corresponding time window."""
        # Map gold_idx to silver_idx proportionally or by datetime
        if silver_has_dt and gold_idx < gold_len:
            target_dt = str(gold_df["datetime"].iloc[gold_idx])
            s_matches = silver_df.index[silver_df["datetime"] == target_dt].tolist()
            s_idx = s_matches[0] if s_matches else int(gold_idx * (silver_len / max(1, gold_len)))
        else:
            s_idx = int(gold_idx * (silver_len / max(1, gold_len)))

        start_i = max(0, s_idx - window)
        end_i = min(silver_len, s_idx + window + 1)
        sub_df = silver_df.iloc[start_i:end_i]
        if len(sub_df) == 0:
            return float(silver_df["close"].iloc[-1])
        if is_high:
            return float(sub_df["high"].max())
        else:
            return float(sub_df["low"].min())

    # 1. Check Bullish SMT: Gold made Lower Low, Silver held Higher Low
    if len(gold_lows) >= 2:
        # Check the most recent 3 pairs of swing lows
        n_lows = len(gold_lows)
        for i in range(n_lows - 1, max(0, n_lows - 4), -1):
            curr_low = gold_lows[i]
            for j in range(i - 1, max(-1, i - 4), -1):
                if j < 0:
                    break
                prev_low = gold_lows[j]
                gl_curr = float(curr_low["price"])
                gl_prev = float(prev_low["price"])

                # Gold must form a Lower Low
                if gl_curr < gl_prev:
                    sl_curr = get_silver_extreme_around(curr_low["index"], window=2, is_high=False)
                    sl_prev = get_silver_extreme_around(prev_low["index"], window=2, is_high=False)

                    # Silver fails to make a lower low (holds higher or equal)
                    if sl_curr >= sl_prev:
                        return {
                            "has_smt": True,
                            "type": "BULLISH_SMT",
                            "reason": f"BULLISH SMT CONFIRMED: Gold swept lower (${gl_curr:.2f} < ${gl_prev:.2f}) while Silver held higher (${sl_curr:.2f} >= ${sl_prev:.2f})",
                            "gold_swing": f"Lower Low (${gl_curr:.2f} vs ${gl_prev:.2f})",
                            "benchmark_swing": f"Higher Low (${sl_curr:.2f} vs ${sl_prev:.2f})",
                            "detail": {
                                "gold_lows": [gl_prev, gl_curr],
                                "silver_lows": [sl_prev, sl_curr],
                                "gold_times": [prev_low.get("datetime"), curr_low.get("datetime")]
                            }
                        }

    # 2. Check Bearish SMT: Gold made Higher High, Silver formed Lower High
    if len(gold_highs) >= 2:
        n_highs = len(gold_highs)
        for i in range(n_highs - 1, max(0, n_highs - 4), -1):
            curr_high = gold_highs[i]
            for j in range(i - 1, max(-1, i - 4), -1):
                if j < 0:
                    break
                prev_high = gold_highs[j]
                gh_curr = float(curr_high["price"])
                gh_prev = float(prev_high["price"])

                # Gold pushed to a Higher High
                if gh_curr > gh_prev:
                    sh_curr = get_silver_extreme_around(curr_high["index"], window=2, is_high=True)
                    sh_prev = get_silver_extreme_around(prev_high["index"], window=2, is_high=True)

                    # Silver fails to confirm (forms lower high or equal)
                    if sh_curr <= sh_prev:
                        return {
                            "has_smt": True,
                            "type": "BEARISH_SMT",
                            "reason": f"BEARISH SMT CONFIRMED: Gold pushed higher (${gh_curr:.2f} > ${gh_prev:.2f}) but Silver failed to confirm (${sh_curr:.2f} <= ${sh_prev:.2f})",
                            "gold_swing": f"Higher High (${gh_curr:.2f} vs ${gh_prev:.2f})",
                            "benchmark_swing": f"Lower High (${sh_curr:.2f} vs ${sh_prev:.2f})",
                            "detail": {
                                "gold_highs": [gh_prev, gh_curr],
                                "silver_highs": [sh_prev, sh_curr],
                                "gold_times": [prev_high.get("datetime"), curr_high.get("datetime")]
                            }
                        }

    # No SMT divergence found
    return {
        "has_smt": False,
        "type": "NONE",
        "reason": "Waiting for SMT divergence: Gold and Silver swings are moving in sync without divergence",
        "detail": {}
    }
