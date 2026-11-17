"""Complete Gold SMC Strategy State Machine & Signal Generator.
Implements the exact 4H -> 1H -> 15M -> 5M institutional rule set.
"""
from datetime import datetime, timezone
import pandas as pd
from typing import Dict, Any, Optional, List
from app.smc.sessions import get_session_info
from app.smc.structure import analyze_order_flow, find_swings
from app.smc.fvg import find_fvgs, check_htf_fvg_mitigation
from app.smc.smt import detect_smt_divergence
from app.config import GOLD_SPREAD_USD, SL_BUFFER_ATR_MULT, MIN_RR_RATIO

def check_three_candles_displacement(df_5m: pd.DataFrame, expected_direction: str = "BULLISH") -> Dict[str, Any]:
    """
    Checks for 3 consecutive green/red displacement candles and 5M FVG.
    Scans the recent 12 bars to detect when 3 displacement candles formed a 5M FVG,
    and whether the FVG remains active and unmitigated / currently retracing to 50% CE.
    """
    if df_5m is None or len(df_5m) < 3:
        return {"passed": False, "reason": "Insufficient 5M bars"}

    n = len(df_5m)
    max_lookback = min(15, n)
    best_candidate = None

    if expected_direction == "BULLISH":
        for end_idx in range(n - 1, max(1, n - max_lookback), -1):
            c1 = df_5m.iloc[end_idx - 2]
            c2 = df_5m.iloc[end_idx - 1]
            c3 = df_5m.iloc[end_idx]

            all_green = (c1["close"] > c1["open"]) and (c2["close"] > c2["open"]) and (c3["close"] > c3["open"])
            displacement = (c3["close"] - c1["open"]) > 0.40  # noticeable displacement
            fvg_formed = float(c3["low"]) > float(c1["high"])
            gap_size = float(c3["low"]) - float(c1["high"]) if fvg_formed else 0.0

            if all_green and (fvg_formed or displacement):
                top = float(c3["low"]) if fvg_formed else float(c3["close"])
                bottom = float(c1["high"]) if fvg_formed else float(c1["open"])
                ce_50 = (top + bottom) / 2.0

                bars_since = df_5m.iloc[end_idx:]
                closed_below = any(bars_since["close"] < bottom) if len(bars_since) > 1 else False

                if not closed_below:
                    bars_ago = (n - 1) - end_idx
                    time_label = f" ({bars_ago} bars ago)" if bars_ago > 0 else " (latest closed candles)"
                    best_candidate = {
                        "passed": True,
                        "all_same_color": True,
                        "fvg_formed": fvg_formed,
                        "direction": "BULLISH",
                        "top": top,
                        "bottom": bottom,
                        "ce_50": ce_50,
                        "gap_size": gap_size,
                        "bars_ago": bars_ago,
                        "reason": f"5M Bullish Displacement & FVG [{bottom:.2f} - {top:.2f}] (50% CE: ${ce_50:.2f}){time_label}"
                    }
                    break

        if best_candidate:
            return best_candidate

        return {
            "passed": False,
            "all_same_color": False,
            "fvg_formed": False,
            "reason": "Waiting for 3 straight green expansion candles & 5M Bullish FVG"
        }

    elif expected_direction == "BEARISH":
        for end_idx in range(n - 1, max(1, n - max_lookback), -1):
            c1 = df_5m.iloc[end_idx - 2]
            c2 = df_5m.iloc[end_idx - 1]
            c3 = df_5m.iloc[end_idx]

            all_red = (c1["close"] < c1["open"]) and (c2["close"] < c2["open"]) and (c3["close"] < c3["open"])
            displacement = (c1["open"] - c3["close"]) > 0.40
            fvg_formed = float(c3["high"]) < float(c1["low"])
            gap_size = float(c1["low"]) - float(c3["high"]) if fvg_formed else 0.0

            if all_red and (fvg_formed or displacement):
                top = float(c1["low"]) if fvg_formed else float(c1["open"])
                bottom = float(c3["high"]) if fvg_formed else float(c3["close"])
                ce_50 = (top + bottom) / 2.0

                bars_since = df_5m.iloc[end_idx:]
                closed_above = any(bars_since["close"] > top) if len(bars_since) > 1 else False

                if not closed_above:
                    bars_ago = (n - 1) - end_idx
                    time_label = f" ({bars_ago} bars ago)" if bars_ago > 0 else " (latest closed candles)"
                    best_candidate = {
                        "passed": True,
                        "all_same_color": True,
                        "fvg_formed": fvg_formed,
                        "direction": "BEARISH",
                        "top": top,
                        "bottom": bottom,
                        "ce_50": ce_50,
                        "gap_size": gap_size,
                        "bars_ago": bars_ago,
                        "reason": f"5M Bearish Displacement & FVG [{bottom:.2f} - {top:.2f}] (50% CE: ${ce_50:.2f}){time_label}"
                    }
                    break

        if best_candidate:
            return best_candidate

        return {
            "passed": False,
            "all_same_color": False,
            "fvg_formed": False,
            "reason": "Waiting for 3 straight red expansion candles & 5M Bearish FVG"
        }

    return {"passed": False, "reason": "Unknown direction"}

def evaluate_strategy(
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_5m: pd.DataFrame,
    silver_df: Optional[pd.DataFrame] = None,
    current_time: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Evaluates the full multi-timeframe strategy:
    Step 1: 4H Macro Trend
    Step 2: 15M Intraday Alignment
    Step 3: 4H / 1H FVG Retracement & Mitigation (Internal Liquidity)
    Step 4: Reversal with SMT Divergence
    Step 5: 5M 3 Consecutive Candles Displacement & 5M FVG
    Step 6: Entry at 50% CE, SL at 5M/15M swing, Target at 5M/15M DOL
    """
    if current_time is None:
        if len(df_5m):
            last_dt = df_5m["datetime"].iloc[-1]
            current_time = pd.to_datetime(last_dt, utc=True).to_pydatetime()
        else:
            current_time = datetime.now(timezone.utc)

    session_info = get_session_info(current_time)

    # 1. 4H Macro Trend & Order Flow
    flow_4h = analyze_order_flow(df_4h)
    trend_4h = flow_4h["trend"]

    # 2. 1H Order Flow
    flow_1h = analyze_order_flow(df_1h)
    trend_1h = flow_1h["trend"]

    # 3. 15M Intraday Alignment & Day Trend
    flow_15m = analyze_order_flow(df_15m)
    trend_15m = flow_15m["trend"]

    # Current Price
    curr_price = float(df_5m["close"].iloc[-1]) if len(df_5m) else float(df_15m["close"].iloc[-1])

    # 4. HTF (4H / 1H) FVG Mitigation Check (Internal Liquidity Retracement)
    fvgs_4h = find_fvgs(df_4h, min_gap_usd=0.50)
    fvgs_1h = find_fvgs(df_1h, min_gap_usd=0.35)
    htf_fvgs = fvgs_4h + fvgs_1h

    # 5. SMT Divergence Check
    smt_info = detect_smt_divergence(df_5m, silver_df)

    # Swing extremes on 5M and 15M for SL and DOL (Draw on Liquidity)
    swings_5m = find_swings(df_5m, window=2)
    swings_15m = find_swings(df_15m, window=2)

    # Gate diagnostics list
    gates = []

    # 4H, 1H, and 15M Order Flow alignment
    is_bullish_bias = (trend_4h == "BULLISH") and (trend_1h in ("BULLISH", "NEUTRAL")) and (trend_15m in ("BULLISH", "NEUTRAL"))
    is_bearish_bias = (trend_4h == "BEARISH") and (trend_1h in ("BEARISH", "NEUTRAL")) and (trend_15m in ("BEARISH", "NEUTRAL"))

    setup_signal = "NEUTRAL"
    trade_plan = None
    reasoning_chain = {}

    if is_bullish_bias:
        # Step 3: HTF Mitigation
        mitigation_check = check_htf_fvg_mitigation(curr_price, htf_fvgs, expected_type="BULLISH")
        htf_mitigated = mitigation_check is not None and mitigation_check["is_mitigated"]

        # Step 4: SMT Check (or momentum divergence)
        smt_passed = smt_info["has_smt"] and smt_info["type"] == "BULLISH_SMT"

        # Step 5: 5M 3 straight green candles displacement
        disp_check = check_three_candles_displacement(df_5m, expected_direction="BULLISH")

        gates.append({"gate": "1. 4H Macro Trend", "status": "PASS", "detail": f"4H Bullish (EMA50: {flow_4h['ema_50']:.2f})"})
        gates.append({"gate": "2. 1H & 15M Order Flow", "status": "PASS", "detail": f"1H: {trend_1h} · 15M: {trend_15m} (Respected & Aligned with 4H)"})
        gates.append({"gate": "3. 4H/1H FVG Retracement (Internal Liquidity)", "status": "PASS" if htf_mitigated else "WAITING", "detail": mitigation_check["detail"] if htf_mitigated else "Waiting for price to retrace into 4H/1H Bullish FVG"})
        gates.append({"gate": "4. SMT Divergence Reversal", "status": "PASS" if smt_passed else "WAITING", "detail": smt_info["reason"]})
        gates.append({"gate": "5. 5M 3-Candle Displacement & FVG", "status": "PASS" if disp_check["passed"] else "WAITING", "detail": disp_check["reason"]})
        gates.append({"gate": "6. Session Killzone", "status": "PASS" if session_info["allowed_to_trade"] else "FILTERED", "detail": session_info["reason"]})

        if htf_mitigated and smt_passed and disp_check["passed"] and session_info["allowed_to_trade"]:
            entry_price = disp_check["ce_50"]
            recent_lows = [s["price"] for s in swings_15m if s["type"] == "LOW"]
            if not recent_lows:
                recent_lows = [s["price"] for s in swings_5m if s["type"] == "LOW"]
            base_low = min(recent_lows[-2:]) if recent_lows else (entry_price - 3.5)
            # Minimum $2.20 stop distance on Gold to survive normal intra-session noise and spread
            risk_distance = max(2.20, entry_price - base_low + GOLD_SPREAD_USD)
            sl_price = entry_price - risk_distance

            recent_highs = [s["price"] for s in swings_15m if s["type"] == "HIGH"]
            dol_high = max(recent_highs[-3:]) if recent_highs else (entry_price + risk_distance * 2.2)
            reward_distance = max(risk_distance * 2.0, dol_high - entry_price)
            dol_target = entry_price + reward_distance
            rr_ratio = reward_distance / risk_distance

            if rr_ratio >= MIN_RR_RATIO:
                setup_signal = "BULLISH_ENTRY"
                trade_plan = {
                    "side": "BUY",
                    "entry_price": round(entry_price, 2),
                    "stop_loss": round(sl_price, 2),
                    "take_profit": round(dol_target, 2),
                    "risk_usd_per_oz": round(risk_distance, 2),
                    "reward_usd_per_oz": round(reward_distance, 2),
                    "rr_ratio": round(rr_ratio, 2),
                    "fvg_top": round(disp_check["top"], 2),
                    "fvg_bottom": round(disp_check["bottom"], 2),
                    "ce_50": round(disp_check["ce_50"], 2),
                    "mitigated_htf_fvg": mitigation_check["fvg"]["id"] if mitigation_check else "HTF_ZONE"
                }

    elif is_bearish_bias:
        # Step 3: HTF Mitigation
        mitigation_check = check_htf_fvg_mitigation(curr_price, htf_fvgs, expected_type="BEARISH")
        htf_mitigated = mitigation_check is not None and mitigation_check["is_mitigated"]

        # Step 4: SMT Check
        smt_passed = smt_info["has_smt"] and smt_info["type"] == "BEARISH_SMT"

        # Step 5: 5M 3 straight red candles displacement
        disp_check = check_three_candles_displacement(df_5m, expected_direction="BEARISH")

        gates.append({"gate": "1. 4H Macro Trend", "status": "PASS", "detail": f"4H Bearish (EMA50: {flow_4h['ema_50']:.2f})"})
        gates.append({"gate": "2. 1H & 15M Order Flow", "status": "PASS", "detail": f"1H: {trend_1h} · 15M: {trend_15m} (Respected & Aligned with 4H)"})
        gates.append({"gate": "3. 4H/1H FVG Retracement (Internal Liquidity)", "status": "PASS" if htf_mitigated else "WAITING", "detail": mitigation_check["detail"] if htf_mitigated else "Waiting for price to retrace into 4H/1H Bearish FVG"})
        gates.append({"gate": "4. SMT Divergence Reversal", "status": "PASS" if smt_passed else "WAITING", "detail": smt_info["reason"]})
        gates.append({"gate": "5. 5M 3-Candle Displacement & FVG", "status": "PASS" if disp_check["passed"] else "WAITING", "detail": disp_check["reason"]})
        gates.append({"gate": "6. Session Killzone", "status": "PASS" if session_info["allowed_to_trade"] else "FILTERED", "detail": session_info["reason"]})

        if htf_mitigated and smt_passed and disp_check["passed"] and session_info["allowed_to_trade"]:
            entry_price = disp_check["ce_50"]
            recent_highs = [s["price"] for s in swings_15m if s["type"] == "HIGH"]
            if not recent_highs:
                recent_highs = [s["price"] for s in swings_5m if s["type"] == "HIGH"]
            base_high = max(recent_highs[-2:]) if recent_highs else (entry_price + 3.5)
            risk_distance = max(2.20, base_high - entry_price + GOLD_SPREAD_USD)
            sl_price = entry_price + risk_distance

            recent_lows = [s["price"] for s in swings_15m if s["type"] == "LOW"]
            dol_low = min(recent_lows[-3:]) if recent_lows else (entry_price - risk_distance * 2.2)
            reward_distance = max(risk_distance * 2.0, entry_price - dol_low)
            dol_target = entry_price - reward_distance
            rr_ratio = reward_distance / risk_distance

            if rr_ratio >= MIN_RR_RATIO:
                setup_signal = "BEARISH_ENTRY"
                trade_plan = {
                    "side": "SELL",
                    "entry_price": round(entry_price, 2),
                    "stop_loss": round(sl_price, 2),
                    "take_profit": round(dol_target, 2),
                    "risk_usd_per_oz": round(risk_distance, 2),
                    "reward_usd_per_oz": round(reward_distance, 2),
                    "rr_ratio": round(rr_ratio, 2),
                    "fvg_top": round(disp_check["top"], 2),
                    "fvg_bottom": round(disp_check["bottom"], 2),
                    "ce_50": round(disp_check["ce_50"], 2),
                    "mitigated_htf_fvg": mitigation_check["fvg"]["id"] if mitigation_check else "HTF_ZONE"
                }

    else:
        disp_bull = check_three_candles_displacement(df_5m, expected_direction="BULLISH")
        disp_bear = check_three_candles_displacement(df_5m, expected_direction="BEARISH")
        if disp_bull["passed"]:
            disp_status = "PASS"
            disp_detail = f"FORMED: {disp_bull['reason']}"
        elif disp_bear["passed"]:
            disp_status = "PASS"
            disp_detail = f"FORMED: {disp_bear['reason']}"
        else:
            disp_status = "WAITING"
            disp_detail = "Waiting for 3 straight expansion candles & 5M FVG"

        gates.append({"gate": "1. 4H Macro Trend", "status": "INFO", "detail": f"4H is {trend_4h}"})
        gates.append({"gate": "2. 1H & 15M Order Flow", "status": "INFO", "detail": f"1H: {trend_1h} · 15M: {trend_15m} (Must align with 4H)"})
        gates.append({"gate": "3. 4H/1H FVG Retracement (Internal Liquidity)", "status": "WAITING", "detail": "Waiting for multi-timeframe trend alignment"})
        gates.append({"gate": "4. SMT Divergence Reversal", "status": "PASS" if smt_info["has_smt"] else "WAITING", "detail": smt_info["reason"]})
        gates.append({"gate": "5. 5M 3-Candle Displacement & FVG", "status": disp_status, "detail": disp_detail})
        gates.append({"gate": "6. Session Killzone", "status": "PASS" if session_info["allowed_to_trade"] else "FILTERED", "detail": session_info["reason"]})

    # Build the full, auditable reasoning chain
    reasoning_chain = {
        "timestamp": current_time.isoformat(),
        "htf_trend_4h": trend_4h,
        "intraday_trend_15m": trend_15m,
        "aligned": is_bullish_bias or is_bearish_bias,
        "session": session_info["session"],
        "killzone_active": session_info["is_killzone"],
        "current_price": curr_price,
        "gates": gates,
        "signal": setup_signal,
        "trade_plan": trade_plan
    }

    return reasoning_chain
