"""Flask Web Application & REST API for Gold SMC Strategy Monitor."""
import os
import json
import pandas as pd
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request
from app.config import (
    GOLD_SYMBOL, BENCHMARK_SYMBOL, WEB_HOST, WEB_PORT
)
from app.database.db import (
    init_db, read_candles, save_candles, log_run,
    get_latest_runs, get_account, get_paper_trades
)
from app.api.market_data import (
    fetch_twelve_data, generate_synthetic_candles, resample_candles
)
from app.smc.strategy import evaluate_strategy
from app.smc.fvg import find_fvgs
from app.paper_trading.engine import (
    process_market_candle, get_performance_summary
)
from app.backtest.runner import run_one_year_backtest

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "..", "..", "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "..", "..", "static")
)

def ensure_initial_market_data():
    """Seeds database with high-resolution Gold & Silver candles if empty."""
    init_db()
    existing_5m = read_candles(GOLD_SYMBOL, "5min", limit=10)
    if not existing_5m:
        # Generate 45 days of 5m candles
        df_gold_5m = generate_synthetic_candles(base_price=2685.0, days=45, interval_minutes=5, seed=77)
        df_silver_5m = generate_synthetic_candles(base_price=31.20, days=45, interval_minutes=5, seed=88)

        # Resample to 15m, 1h, 4h
        df_gold_15m = resample_candles(df_gold_5m, "15min")
        df_gold_1h = resample_candles(df_gold_5m, "1h")
        df_gold_4h = resample_candles(df_gold_5m, "4h")

        save_candles(GOLD_SYMBOL, "5min", df_gold_5m.to_dict(orient="records"))
        save_candles(GOLD_SYMBOL, "15min", df_gold_15m.to_dict(orient="records"))
        save_candles(GOLD_SYMBOL, "1h", df_gold_1h.to_dict(orient="records"))
        save_candles(GOLD_SYMBOL, "4h", df_gold_4h.to_dict(orient="records"))

        save_candles(BENCHMARK_SYMBOL, "5min", df_silver_5m.to_dict(orient="records"))
        log_run(GOLD_SYMBOL, "ALL_TIMEFRAMES", len(df_gold_5m), "OK", "Initialized multi-timeframe market candles")

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "app": "gold-smc-monitor",
        "mode": "READ_ONLY_SIMULATION",
        "symbol": GOLD_SYMBOL,
        "benchmark": BENCHMARK_SYMBOL
    })

@app.get("/api/market")
def get_market_state():
    """Returns current live multi-timeframe strategy state, gates, and signal."""
    ensure_initial_market_data()

    c_5m = read_candles(GOLD_SYMBOL, "5min", limit=120)
    c_15m = read_candles(GOLD_SYMBOL, "15min", limit=100)
    c_1h = read_candles(GOLD_SYMBOL, "1h", limit=80)
    c_4h = read_candles(GOLD_SYMBOL, "4h", limit=60)
    c_silver = read_candles(BENCHMARK_SYMBOL, "5min", limit=60)

    df_5m = pd.DataFrame(c_5m)
    df_15m = pd.DataFrame(c_15m)
    df_1h = pd.DataFrame(c_1h)
    df_4h = pd.DataFrame(c_4h)
    df_silver = pd.DataFrame(c_silver) if c_silver else None

    state = evaluate_strategy(df_4h, df_1h, df_15m, df_5m, df_silver)

    # Also detect active FVGs for chart overlays
    fvgs_5m = find_fvgs(df_5m, min_gap_usd=0.25) if len(df_5m) else []
    fvgs_1h = find_fvgs(df_1h, min_gap_usd=0.50) if len(df_1h) else []

    last_candle = c_5m[-1] if c_5m else None

    return jsonify({
        "symbol": GOLD_SYMBOL,
        "benchmark": BENCHMARK_SYMBOL,
        "last_candle": last_candle,
        "strategy": state,
        "active_fvgs_5m": fvgs_5m[-6:],
        "active_fvgs_1h": fvgs_1h[-4:]
    })

@app.get("/api/history")
def get_history():
    """Returns candle history for the selected timeframe."""
    interval = request.args.get("interval", "5min")
    limit = min(1000, max(50, int(request.args.get("limit", 300))))
    rows = read_candles(GOLD_SYMBOL, interval, limit=limit)
    return jsonify(rows)

@app.get("/api/paper/summary")
def get_paper_summary():
    return jsonify(get_performance_summary())

@app.get("/api/paper/trades")
def get_paper_trade_list():
    status = request.args.get("status")
    side = request.args.get("side")
    outcome = request.args.get("outcome")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    search = request.args.get("search")
    limit = min(500, max(1, int(request.args.get("limit", 200))))
    return jsonify(get_paper_trades(
        status=status,
        side=side,
        outcome=outcome,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit
    ))

@app.get("/api/backtest")
def get_backtest_data():
    version = request.args.get("version", "v2")
    force = request.args.get("force", "false").lower() in ("1", "true")
    results = run_one_year_backtest(version=version, force_refresh=force)
    return jsonify(results)

@app.get("/api/activity")
def get_activity():
    status = request.args.get("status")
    interval = request.args.get("interval")
    search = request.args.get("search")
    limit = min(200, max(1, int(request.args.get("limit", 50))))
    return jsonify(get_latest_runs(status=status, interval=interval, search=search, limit=limit))

from app.api.market_data import (
    fetch_twelve_data, generate_synthetic_candles, resample_candles,
    fetch_latest_market_bars
)
import threading
import time

def run_collection_cycle_internal():
    """Internal helper to fetch live bars, evaluate strategy, and process paper orders."""
    try:
        ensure_initial_market_data()

        # 1. Ingest fresh live market bars (Yahoo Finance GC=F / SI=F or Twelve Data)
        live_gold_df = fetch_latest_market_bars(GOLD_SYMBOL)
        if live_gold_df is not None and len(live_gold_df) > 0:
            save_candles(GOLD_SYMBOL, "5min", live_gold_df.to_dict(orient="records"))
            # Resample and save HTFs
            df_15m = resample_candles(live_gold_df, "15min")
            df_1h = resample_candles(live_gold_df, "1h")
            df_4h = resample_candles(live_gold_df, "4h")
            if len(df_15m) > 0: save_candles(GOLD_SYMBOL, "15min", df_15m.to_dict(orient="records"))
            if len(df_1h) > 0: save_candles(GOLD_SYMBOL, "1h", df_1h.to_dict(orient="records"))
            if len(df_4h) > 0: save_candles(GOLD_SYMBOL, "4h", df_4h.to_dict(orient="records"))

        live_silver_df = fetch_latest_market_bars(BENCHMARK_SYMBOL)
        if live_silver_df is not None and len(live_silver_df) > 0:
            save_candles(BENCHMARK_SYMBOL, "5min", live_silver_df.to_dict(orient="records"))

        # 2. Read latest multi-timeframe candles
        c_5m = read_candles(GOLD_SYMBOL, "5min", limit=120)
        c_15m = read_candles(GOLD_SYMBOL, "15min", limit=100)
        c_1h = read_candles(GOLD_SYMBOL, "1h", limit=80)
        c_4h = read_candles(GOLD_SYMBOL, "4h", limit=60)
        c_silver = read_candles(BENCHMARK_SYMBOL, "5min", limit=60)

        df_5m = pd.DataFrame(c_5m)
        df_15m = pd.DataFrame(c_15m)
        df_1h = pd.DataFrame(c_1h)
        df_4h = pd.DataFrame(c_4h)
        df_silver = pd.DataFrame(c_silver) if c_silver else None

        # 3. Strategy evaluation
        state = evaluate_strategy(df_4h, df_1h, df_15m, df_5m, df_silver)

        # 4. Process latest candle in paper trading engine
        events = {}
        if c_5m:
            events = process_market_candle(c_5m[-1], state)

        log_run(GOLD_SYMBOL, "5min", len(c_5m), "OK", f"Live cycle evaluated. Signal: {state.get('signal')}")
        return {"status": "cycle_completed", "signal": state.get("signal"), "events": events}
    except Exception as e:
        log_run(GOLD_SYMBOL, "5min", 0, "ERROR", f"Cycle failed: {str(e)[:300]}")
        return {"status": "error", "message": str(e)}

_collector_started = False
def _background_collector_loop():
    time.sleep(5) # initial grace period
    while True:
        try:
            with app.app_context():
                run_collection_cycle_internal()
        except Exception:
            pass
        time.sleep(60) # Runs automatically every 60s

def ensure_background_collector_running():
    global _collector_started
    if not _collector_started:
        _collector_started = True
        t = threading.Thread(target=_background_collector_loop, daemon=True)
        t.start()

@app.post("/api/collect-cycle")
def run_collection_cycle():
    """Manual or frontend evaluation trigger."""
    result = run_collection_cycle_internal()
    return jsonify(result)

@app.get("/")
def index():
    ensure_background_collector_running()
    return render_template("index.html", symbol=GOLD_SYMBOL, benchmark=BENCHMARK_SYMBOL)
