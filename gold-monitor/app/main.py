"""CLI Entry Point for Gold SMC Strategy Monitor."""
import sys
import time
import argparse
import logging
from app.config import WEB_HOST, WEB_PORT, GOLD_SYMBOL, BENCHMARK_SYMBOL
from app.database.db import init_db, log_run
from app.web.routes import app, ensure_initial_market_data, run_collection_cycle
from app.backtest.runner import run_one_year_backtest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main():
    parser = argparse.ArgumentParser(description="Gold SMC Strategy Monitor & Paper Trading App")
    parser.add_argument("command", choices=["init-db", "collect-once", "run-collector", "run-backtest", "web"],
                        help="Action to perform")
    parser.add_argument("--port", type=int, default=WEB_PORT, help="Port for web server")
    parser.add_argument("--host", default=WEB_HOST, help="Host for web server")
    parser.add_argument("--force", action="store_true", help="Force backtest recalculation")

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
        ensure_initial_market_data()
        print("Database initialized and market candles seeded.")

    elif args.command == "collect-once":
        init_db()
        ensure_initial_market_data()
        with app.app_context():
            res = run_collection_cycle().get_json()
        print("Cycle Result:", res)

    elif args.command == "run-collector":
        init_db()
        ensure_initial_market_data()
        logging.info("Starting continuous Gold SMC collector (polling every 60s)...")
        while True:
            try:
                with app.app_context():
                    run_collection_cycle()
                logging.info("Collector cycle completed.")
            except Exception as e:
                logging.error(f"Collector error: {e}")
            time.sleep(60)

    elif args.command == "run-backtest":
        init_db()
        print("Running 1-Year Historical Backtest for Gold SMC Strategy...")
        res = run_one_year_backtest(force_refresh=args.force)
        m = res["metrics"]
        print("=" * 60)
        print(f"1-YEAR BACKTEST REPORT: {m['symbol']}")
        print("=" * 60)
        print(f"Initial Capital:     ${m['initial_capital']:,.2f}")
        print(f"Final Equity:        ${m['final_equity']:,.2f}")
        print(f"Net Profit:          ${m['net_profit_usd']:,.2f} ({m['return_pct']:+.2f}%)")
        print(f"Total Trades:        {m['total_trades']} (Wins: {m['winning_trades']}, Losses: {m['losing_trades']})")
        print(f"Win Rate:            {m['win_rate_pct']:.1f}%")
        print(f"Profit Factor:       {m['profit_factor']:.2f}")
        print(f"Average R-Multiple:  {m['average_r_multiple']:.2f}R")
        print(f"Max Drawdown:        ${m['max_drawdown_usd']:,.2f} ({m['max_drawdown_pct']:.1f}%)")
        print(f"Sharpe Ratio:        {m['sharpe_ratio']:.2f}")
        print("=" * 60)

    elif args.command == "web":
        init_db()
        ensure_initial_market_data()
        print(f"Starting Gold SMC Monitor on http://{args.host}:{args.port}")
        app.run(host=args.host, port=args.port, debug=False)

if __name__ == "__main__":
    main()
