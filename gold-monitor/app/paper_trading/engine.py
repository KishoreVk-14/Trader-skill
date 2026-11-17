"""Automated Paper Trading Engine for Gold SMC Strategy."""
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from app.config import (
    INITIAL_CAPITAL, RISK_PER_TRADE_PCT, MAX_OPEN_POSITIONS,
    MAX_LEVERAGE, GOLD_SPREAD_USD, GOLD_SYMBOL
)
from app.database.db import (
    connect, init_db, get_account, update_account_balance,
    get_paper_trades
)

logger = logging.getLogger(__name__)

def process_market_candle(candle: Dict[str, Any], signal_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Called whenever a new closed 5M candle arrives.
    1. Evaluates all open trades for SL or TP hits.
    2. If a valid BULLISH_ENTRY or BEARISH_ENTRY signal is fired and capacity exists, opens a new paper trade.
    """
    init_db()
    c_time = candle["datetime"]
    c_open = float(candle["open"])
    c_high = float(candle["high"])
    c_low = float(candle["low"])
    c_close = float(candle["close"])

    closed_events = []
    opened_events = []

    # 1. Evaluate open trades
    with connect() as conn:
        open_rows = conn.execute("SELECT * FROM gold_paper_trades WHERE status='OPEN'").fetchall()
        open_trades = [dict(r) for r in open_rows]

    for t in open_trades:
        side = t["side"]
        entry_price = float(t["entry_price"])
        sl = float(t["stop_loss"])
        tp = float(t["take_profit"])
        units = float(t["units"])
        trade_id = t["id"]

        hit_sl = False
        hit_tp = False

        if side in ("BUY", "LONG"):
            if c_low <= sl:
                hit_sl = True
            if c_high >= tp:
                hit_tp = True

            # If both hit in the same bar, assume pessimistic SL hit
            if hit_sl and hit_tp:
                exit_price = sl
                exit_reason = "STOP_LOSS (Pessimistic tie-breaker)"
            elif hit_sl:
                exit_price = sl
                exit_reason = "STOP_LOSS"
            elif hit_tp:
                exit_price = tp
                exit_reason = "TAKE_PROFIT"
            else:
                continue

            pnl = (exit_price - entry_price) * units
            risk = float(t["risk_usd"])
            r_mult = pnl / risk if risk > 0 else 0.0

            with connect() as conn:
                conn.execute("""
                    UPDATE gold_paper_trades
                    SET status='CLOSED', exit_time=?, exit_price=?, exit_reason=?, pnl_usd=?, r_multiple=?
                    WHERE id=? AND status='OPEN'
                """, (c_time, exit_price, exit_reason, pnl, r_mult, trade_id))
            update_account_balance(pnl)
            closed_events.append({"id": trade_id, "reason": exit_reason, "pnl": pnl, "r": r_mult})

        elif side in ("SELL", "SHORT"):
            if c_high >= sl:
                hit_sl = True
            if c_low <= tp:
                hit_tp = True

            if hit_sl and hit_tp:
                exit_price = sl
                exit_reason = "STOP_LOSS (Pessimistic tie-breaker)"
            elif hit_sl:
                exit_price = sl
                exit_reason = "STOP_LOSS"
            elif hit_tp:
                exit_price = tp
                exit_reason = "TAKE_PROFIT"
            else:
                continue

            pnl = (entry_price - exit_price) * units
            risk = float(t["risk_usd"])
            r_mult = pnl / risk if risk > 0 else 0.0

            with connect() as conn:
                conn.execute("""
                    UPDATE gold_paper_trades
                    SET status='CLOSED', exit_time=?, exit_price=?, exit_reason=?, pnl_usd=?, r_multiple=?
                    WHERE id=? AND status='OPEN'
                """, (c_time, exit_price, exit_reason, pnl, r_mult, trade_id))
            update_account_balance(pnl)
            closed_events.append({"id": trade_id, "reason": exit_reason, "pnl": pnl, "r": r_mult})

    # 2. Check if a new trade should be opened
    plan = signal_result.get("trade_plan")
    sig = signal_result.get("signal")

    if plan and sig in ("BULLISH_ENTRY", "BEARISH_ENTRY"):
        with connect() as conn:
            current_open = conn.execute("SELECT COUNT(*) FROM gold_paper_trades WHERE status='OPEN'").fetchone()[0]

        if current_open < MAX_OPEN_POSITIONS:
            # Check price limit fill: entry is at 50% CE of 5M FVG
            ce_50 = plan["entry_price"]
            sl = plan["stop_loss"]
            tp = plan["take_profit"]
            side = plan["side"]

            can_fill = False
            if side == "BUY" and c_low <= ce_50:
                can_fill = True
            elif side == "SELL" and c_high >= ce_50:
                can_fill = True

            if can_fill:
                acct = get_account()
                equity = acct["cash_balance"]
                risk_usd = equity * RISK_PER_TRADE_PCT
                risk_dist = abs(ce_50 - sl)

                if risk_dist > 0.20:
                    units = min(risk_usd / risk_dist, (equity * MAX_LEVERAGE) / ce_50)
                    units = max(0.1, round(units, 2))  # minimum 0.1 oz of gold

                    setup_json = json.dumps({
                        "4h_trend": signal_result.get("htf_trend_4h"),
                        "15m_trend": signal_result.get("intraday_trend_15m"),
                        "session": signal_result.get("session"),
                        "fvg_top": plan.get("fvg_top"),
                        "fvg_bottom": plan.get("fvg_bottom"),
                        "ce_50": plan.get("ce_50"),
                        "mitigated_htf_fvg": plan.get("mitigated_htf_fvg"),
                        "rr_ratio": plan.get("rr_ratio"),
                        "gates": signal_result.get("gates")
                    })

                    with connect() as conn:
                        cur = conn.execute("""
                            INSERT INTO gold_paper_trades (
                                symbol, side, status, entry_time, entry_price, units,
                                stop_loss, take_profit, risk_usd, setup_details, created_at
                            )
                            VALUES (?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        """, (
                            GOLD_SYMBOL, side, c_time, ce_50, units,
                            sl, tp, risk_usd, setup_json
                        ))
                        new_id = cur.lastrowid
                    opened_events.append({"id": new_id, "side": side, "price": ce_50, "units": units})

    return {"closed": closed_events, "opened": opened_events}

def get_performance_summary() -> Dict[str, Any]:
    """Computes comprehensive paper trading performance stats."""
    acct = get_account()
    trades = get_paper_trades(limit=500)
    closed = [t for t in trades if t["status"] == "CLOSED"]
    open_trades = [t for t in trades if t["status"] == "OPEN"]

    wins = [t for t in closed if (t["pnl_usd"] or 0) > 0]
    losses = [t for t in closed if (t["pnl_usd"] or 0) <= 0]

    gross_profit = sum(t["pnl_usd"] for t in wins)
    gross_loss = abs(sum(t["pnl_usd"] for t in losses))

    win_rate = (len(wins) / len(closed) * 100.0) if closed else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
    avg_r = (sum(t.get("r_multiple", 0) or 0 for t in closed) / len(closed)) if closed else 0.0

    return {
        "initial_capital": acct["initial_capital"],
        "cash_balance": round(acct["cash_balance"], 2),
        "total_trades": len(closed),
        "open_positions": len(open_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "gross_profit_usd": round(gross_profit, 2),
        "gross_loss_usd": round(gross_loss, 2),
        "net_pnl_usd": round(acct["cash_balance"] - acct["initial_capital"], 2),
        "average_r": round(avg_r, 2)
    }
