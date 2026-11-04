#!/usr/bin/env python3
"""Multi-Market Backtesting Engine for day-trader-skill.
Supports Opening-Range Breakouts (ORB) across:
  1. US Stocks (NYSE / NASDAQ)
  2. Indian Stocks (NSE / BSE: .NS, .BO)
  3. Crypto (24/7: BTC-USD, ETH-USD, SOL-USD)
  4. Forex (24/5: EURUSD=X, GBPUSD=X, USDJPY=X)

Modes:
  --mode enhanced (default):
    - Bi-directional trading (Long above OR High, Short below OR Low)
    - 20-period Exponential Moving Average (EMA) trend filter
    - Institutional volume spike confirmation (>= 0.85x OR avg volume)
    - Market-tailored session windows (India 15m, US/Forex 30m, Crypto 60m)
  --mode raw:
    - Original unconstrained long-only 15-minute ORB

Standard library only.
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Ensure local directory is on sys.path
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
if LOCAL_DIR not in sys.path:
    sys.path.insert(0, LOCAL_DIR)

import market as trader_market

UA = "Mozilla/5.0 (compatible; day-trader-multimarket/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
HOSTS = ("query2", "query1")
CACHE_DIR = os.path.join("trader", "cache")


def ensure_cache_dir():
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def calc_ema(prices, period=20):
    if not prices:
        return []
    k = 2.0 / (period + 1)
    ema = [prices[0]]
    for p in prices[1:]:
        ema.append(p * k + ema[-1] * (1.0 - k))
    return ema


def fetch_yahoo_chart_5m(symbol, range_str="60d"):
    """Fetch 60 days of 5-minute bars from Yahoo Finance with disk caching."""
    ensure_cache_dir()
    norm_sym = trader_market.normalize_yahoo_symbol(symbol)
    safe_name = norm_sym.replace("=", "_").replace("^", "_")
    cache_file = os.path.join(CACHE_DIR, f"{safe_name}_{range_str}_5m.json")

    # If cache exists and is newer than 4 hours, use it
    if os.path.isfile(cache_file):
        age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600.0
        if age_hours < 4.0:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

    # Fetch fresh
    encoded_sym = urllib.parse.quote(norm_sym, safe="")
    path = f"/v8/finance/chart/{encoded_sym}?range={range_str}&interval=5m"
    data = None
    for host in HOSTS:
        url = f"https://{host}.finance.yahoo.com{path}"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        for attempt in (0, 1):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read().decode("utf-8")
                    data = json.loads(raw)
                    break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt == 0:
                    time.sleep(3.0)
                    continue
                break
            except Exception:
                break
        if data and "chart" in data and data["chart"].get("result"):
            break

    if not data or "chart" not in data or not data["chart"].get("result"):
        if os.path.isfile(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        raise RuntimeError(f"Could not fetch chart data for {symbol}")

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def parse_bars(chart_json):
    """Parse raw Yahoo chart JSON into sorted list of complete OHLCV bar dicts."""
    res = chart_json["chart"]["result"][0]
    timestamps = res.get("timestamp") or []
    quote = res["indicators"]["quote"][0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    bars = []
    for i, t in enumerate(timestamps):
        if i >= len(opens) or i >= len(highs) or i >= len(lows) or i >= len(closes):
            continue
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        if None in (o, h, l, c):
            continue
        v = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
        dt_utc = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).replace(tzinfo=None)
        bars.append({
            "timestamp": t,
            "dt_utc": dt_utc,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(v)
        })
    bars.sort(key=lambda x: x["timestamp"])

    if bars:
        closes = [b["close"] for b in bars]
        ema20 = calc_ema(closes, 20)
        for i, b in enumerate(bars):
            b["ema"] = ema20[i]

    return bars


def group_bars_by_session(bars, market):
    """Group bars into trading sessions according to market rules."""
    spec = trader_market.get_market_spec(market)
    tz_offset = datetime.timedelta(hours=spec["tz_offset_hours"])
    sessions = {}

    for b in bars:
        dt_local = b["dt_utc"] + tz_offset
        d = dt_local.date()
        t = dt_local.time()

        if market == trader_market.MARKET_US:
            if dt_local.weekday() >= 5:
                continue
            if datetime.time(9, 30) <= t <= datetime.time(16, 0):
                sessions.setdefault(d.isoformat(), []).append(dict(b, dt_local=dt_local))
        elif market == trader_market.MARKET_INDIA:
            if dt_local.weekday() >= 5:
                continue
            if datetime.time(9, 15) <= t <= datetime.time(15, 30):
                sessions.setdefault(d.isoformat(), []).append(dict(b, dt_local=dt_local))
        elif market == trader_market.MARKET_CRYPTO:
            sessions.setdefault(d.isoformat(), []).append(dict(b, dt_local=dt_local))
        elif market == trader_market.MARKET_FOREX:
            if dt_local.weekday() == 5:
                continue
            if datetime.time(8, 0) <= t <= datetime.time(21, 0):
                sessions.setdefault(d.isoformat(), []).append(dict(b, dt_local=dt_local))

    return sessions


def backtest_symbol_orb(symbol, market=None, or_bars=None, r_multiple=None, stop_type="mid", mode="enhanced"):
    """Run Opening Range Breakout (ORB) backtest on a single symbol."""
    if market is None:
        market = trader_market.detect_market(symbol)

    chart_json = fetch_yahoo_chart_5m(symbol, "60d")
    bars = parse_bars(chart_json)
    if not bars:
        return {"symbol": symbol, "market": market, "trades": [], "error": "No bars"}

    sessions = group_bars_by_session(bars, market)
    trades = []

    # Market-tailored defaults in enhanced mode
    if or_bars is None:
        if mode == "enhanced":
            or_bars = 3 if market == trader_market.MARKET_INDIA else (12 if market == trader_market.MARKET_CRYPTO else 6)
        else:
            or_bars = 3

    if r_multiple is None:
        if mode == "enhanced":
            r_multiple = 1.0 if market in (trader_market.MARKET_US, trader_market.MARKET_INDIA) else 1.5
        else:
            r_multiple = 1.5

    for s_date, s_bars in sorted(sessions.items()):
        if len(s_bars) < or_bars + 8:
            continue

        or_slice = s_bars[:or_bars]
        or_high = max(b["high"] for b in or_slice)
        or_low = min(b["low"] for b in or_slice)
        or_range = or_high - or_low
        if or_range <= 0:
            continue

        avg_vol = sum(b["volume"] for b in or_slice) / float(or_bars)
        trade = None
        trade_start = None

        max_search = min(len(s_bars) - 1, or_bars + 18) if mode == "enhanced" else len(s_bars) - 1

        for idx in range(or_bars, max_search):
            bar = s_bars[idx]
            # Long breakout
            if bar["close"] > or_high:
                if mode == "enhanced":
                    if bar["close"] <= bar.get("ema", bar["close"]):
                        pass  # Against trend
                    elif avg_vol > 0 and bar["volume"] < 0.85 * avg_vol:
                        pass  # Weak volume
                    else:
                        stop_price = round((or_high + or_low) / 2.0, 4) if stop_type == "mid" else round(or_low, 4)
                        risk = bar["close"] - stop_price
                        if risk > 0:
                            trade = {
                                "date": s_date, "symbol": symbol, "market": market, "side": "long",
                                "entry_time": bar["dt_local"].strftime("%H:%M"), "entry_price": bar["close"],
                                "stop_price": stop_price, "target_price": round(bar["close"] + risk * r_multiple, 4),
                                "risk_per_unit": risk, "r_target": r_multiple
                            }
                            trade_start = idx + 1
                            break
                else:
                    stop_price = round((or_high + or_low) / 2.0, 4) if stop_type == "mid" else round(or_low, 4)
                    risk = bar["close"] - stop_price
                    if risk > 0:
                        trade = {
                            "date": s_date, "symbol": symbol, "market": market, "side": "long",
                            "entry_time": bar["dt_local"].strftime("%H:%M"), "entry_price": bar["close"],
                            "stop_price": stop_price, "target_price": round(bar["close"] + risk * r_multiple, 4),
                            "risk_per_unit": risk, "r_target": r_multiple
                        }
                        trade_start = idx + 1
                        break

            # Short breakout (Enhanced bi-directional)
            elif mode == "enhanced" and bar["close"] < or_low:
                if bar["close"] >= bar.get("ema", bar["close"]):
                    pass  # Against trend
                elif avg_vol > 0 and bar["volume"] < 0.85 * avg_vol:
                    pass  # Weak volume
                else:
                    stop_price = round((or_high + or_low) / 2.0, 4) if stop_type == "mid" else round(or_high, 4)
                    risk = stop_price - bar["close"]
                    if risk > 0:
                        trade = {
                            "date": s_date, "symbol": symbol, "market": market, "side": "short",
                            "entry_time": bar["dt_local"].strftime("%H:%M"), "entry_price": bar["close"],
                            "stop_price": stop_price, "target_price": round(bar["close"] - risk * r_multiple, 4),
                            "risk_per_unit": risk, "r_target": r_multiple
                        }
                        trade_start = idx + 1
                        break

        # Manage active trade
        if trade and trade_start is not None:
            for bar in s_bars[trade_start:]:
                if trade["side"] == "long":
                    if bar["low"] <= trade["stop_price"]:
                        trade["exit_price"] = trade["stop_price"]
                        trade["exit_time"] = bar["dt_local"].strftime("%H:%M")
                        trade["exit_reason"] = "STOP"
                        trade["r_earned"] = -1.0
                        trade["pnl_pct"] = ((trade["stop_price"] - trade["entry_price"]) / trade["entry_price"]) * 100.0
                        trades.append(trade)
                        trade = None
                        break
                    elif bar["high"] >= trade["target_price"]:
                        trade["exit_price"] = trade["target_price"]
                        trade["exit_time"] = bar["dt_local"].strftime("%H:%M")
                        trade["exit_reason"] = "TARGET"
                        trade["r_earned"] = r_multiple
                        trade["pnl_pct"] = ((trade["target_price"] - trade["entry_price"]) / trade["entry_price"]) * 100.0
                        trades.append(trade)
                        trade = None
                        break
                else:  # short
                    if bar["high"] >= trade["stop_price"]:
                        trade["exit_price"] = trade["stop_price"]
                        trade["exit_time"] = bar["dt_local"].strftime("%H:%M")
                        trade["exit_reason"] = "STOP"
                        trade["r_earned"] = -1.0
                        trade["pnl_pct"] = ((trade["entry_price"] - trade["stop_price"]) / trade["entry_price"]) * 100.0
                        trades.append(trade)
                        trade = None
                        break
                    elif bar["low"] <= trade["target_price"]:
                        trade["exit_price"] = trade["target_price"]
                        trade["exit_time"] = bar["dt_local"].strftime("%H:%M")
                        trade["exit_reason"] = "TARGET"
                        trade["r_earned"] = r_multiple
                        trade["pnl_pct"] = ((trade["entry_price"] - trade["target_price"]) / trade["entry_price"]) * 100.0
                        trades.append(trade)
                        trade = None
                        break

            # Flat by close if still open
            if trade:
                last_bar = s_bars[-1]
                trade["exit_price"] = last_bar["close"]
                trade["exit_time"] = last_bar["dt_local"].strftime("%H:%M")
                trade["exit_reason"] = "FLAT_CLOSE"
                if trade["side"] == "long":
                    diff = trade["exit_price"] - trade["entry_price"]
                else:
                    diff = trade["entry_price"] - trade["exit_price"]
                r_earned = round(diff / trade["risk_per_unit"], 2)
                trade["r_earned"] = r_earned
                trade["pnl_pct"] = (diff / trade["entry_price"]) * 100.0
                trades.append(trade)

    return calculate_stats(symbol, market, trades)


def calculate_stats(symbol, market, trades):
    """Compute quantitative trading metrics for trade set."""
    if not trades:
        return {
            "symbol": symbol, "market": market, "total_trades": 0, "wins": 0, "losses": 0, "flats": 0,
            "win_rate": 0.0, "total_r": 0.0, "profit_factor": 0.0, "avg_r": 0.0, "max_drawdown_r": 0.0,
            "trades": []
        }

    wins = [t for t in trades if t["r_earned"] > 0]
    losses = [t for t in trades if t["r_earned"] < 0]
    flats = [t for t in trades if t["r_earned"] == 0]

    gross_profit_r = sum(t["r_earned"] for t in wins)
    gross_loss_r = abs(sum(t["r_earned"] for t in losses))
    total_r = sum(t["r_earned"] for t in trades)
    profit_factor = round(gross_profit_r / gross_loss_r, 2) if gross_loss_r > 0 else (99.0 if gross_profit_r > 0 else 0.0)

    cum_r, peak_r, max_dd_r = 0.0, 0.0, 0.0
    for t in trades:
        cum_r += t["r_earned"]
        if cum_r > peak_r:
            peak_r = cum_r
        dd = peak_r - cum_r
        if dd > max_dd_r:
            max_dd_r = dd

    win_rate = round((len(wins) / len(trades)) * 100.0, 1)
    avg_r = round(total_r / len(trades), 2)

    return {
        "symbol": symbol,
        "market": market,
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "win_rate": win_rate,
        "total_r": round(total_r, 2),
        "profit_factor": profit_factor,
        "avg_r": avg_r,
        "max_drawdown_r": round(max_dd_r, 2),
        "trades": trades
    }


def run_benchmark(mode="enhanced"):
    symbols_by_market = {
        trader_market.MARKET_US: ["TSLA", "AAPL", "NVDA"],
        trader_market.MARKET_INDIA: ["RELIANCE.NS", "TCS.NS", "INFY.NS"],
        trader_market.MARKET_CRYPTO: ["BTC-USD", "ETH-USD", "SOL-USD"],
        trader_market.MARKET_FOREX: ["EURUSD=X", "GBPUSD=X"]
    }

    results = {}
    for mkt, symbols in symbols_by_market.items():
        results[mkt] = []
        for s in symbols:
            try:
                res = backtest_symbol_orb(s, market=mkt, mode=mode)
                results[mkt].append(res)
            except Exception as e:
                results[mkt].append({"symbol": s, "market": mkt, "total_trades": 0, "error": str(e), "trades": []})

    return results


def print_report(results, mode="enhanced"):
    print("=" * 82)
    mode_title = "ENHANCED QUANTITATIVE ORB (TREND + VOLUME + BI-DIRECTIONAL)" if mode == "enhanced" else "RAW ORB (LONG ONLY)"
    print(f"  {mode_title}")
    print("=" * 82)
    print(f"{'Market':<14} {'Symbol':<14} {'Trades':<8} {'Win Rate':<10} {'Total R':<10} {'Profit Factor':<14} {'Avg R':<8}")
    print("-" * 82)

    market_labels = {
        trader_market.MARKET_US: "US Stocks",
        trader_market.MARKET_INDIA: "Indian Stocks",
        trader_market.MARKET_CRYPTO: "Crypto (24/7)",
        trader_market.MARKET_FOREX: "Forex (24/5)"
    }

    grand_total_trades, grand_total_wins, grand_total_r = 0, 0, 0.0

    for mkt, items in results.items():
        m_name = market_labels.get(mkt, mkt)
        for item in items:
            sym = item.get("symbol", "")
            n = item.get("total_trades", 0)
            if n == 0:
                print(f"{m_name:<14} {sym:<14} {'0':<8} {'N/A':<10} {'0.0':<10} {'N/A':<14} {'0.0':<8}")
                continue
            wr = f"{item['win_rate']}%"
            tot_r = f"{item['total_r']:+.2f}R"
            pf = f"{item['profit_factor']}"
            avg_r = f"{item['avg_r']:+.2f}R"
            print(f"{m_name:<14} {sym:<14} {n:<8} {wr:<10} {tot_r:<10} {pf:<14} {avg_r:<8}")

            grand_total_trades += n
            grand_total_wins += item.get("wins", 0)
            grand_total_r += item.get("total_r", 0.0)

    print("-" * 82)
    overall_wr = round((grand_total_wins / grand_total_trades * 100), 1) if grand_total_trades else 0
    print(f"{'OVERALL':<14} {'ALL MARKETS':<14} {grand_total_trades:<8} {f'{overall_wr}%':<10} {f'{grand_total_r:+.2f}R':<10}")
    print("=" * 82)


def main():
    parser = argparse.ArgumentParser(description="Multi-market backtester for day-trader-skill.")
    parser.add_argument("--symbols", help="Comma-separated symbols to backtest")
    parser.add_argument("--market", choices=["us", "india", "crypto", "forex"], help="Explicit market choice")
    parser.add_argument("--mode", choices=["enhanced", "raw"], default="enhanced", help="enhanced (default) or raw")
    parser.add_argument("--r", type=float, default=None, help="Target R multiple")
    parser.add_argument("--or-minutes", type=int, default=None, help="Opening range minutes")
    parser.add_argument("--stop", choices=["mid", "low"], default="mid", help="Stop type: mid or low")
    parser.add_argument("--all", action="store_true", help="Run full benchmark across US, India, Crypto, Forex")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--write", action="store_true", help="Save output to trader/backtest_results.json")
    args = parser.parse_args()

    or_bars = (args.or_minutes // 5) if args.or_minutes else None

    if args.all or not args.symbols:
        results = run_benchmark(mode=args.mode)
    else:
        syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        results = {}
        for s in syms:
            m = args.market or trader_market.detect_market(s)
            res = backtest_symbol_orb(s, market=m, or_bars=or_bars, r_multiple=args.r, stop_type=args.stop, mode=args.mode)
            results.setdefault(m, []).append(res)

    if args.write:
        ensure_cache_dir()
        out_path = os.path.join("trader", "backtest_results.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Wrote {out_path}")

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results, mode=args.mode)


if __name__ == "__main__":
    main()
