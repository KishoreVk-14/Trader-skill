"""Database module for Gold SMC Monitor."""
import os
import json
import sqlite3
from typing import List, Dict, Any, Optional
from app.config import DB_PATH, INITIAL_CAPITAL

def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    with connect() as conn:
        # Candle store
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gold_candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                candle_time TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, interval, candle_time)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_lookup ON gold_candles(symbol, interval, candle_time)")

        # Paper Account
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gold_paper_account (
                id INTEGER PRIMARY KEY CHECK(id=1),
                initial_capital REAL NOT NULL,
                cash_balance REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO gold_paper_account (id, initial_capital, cash_balance, created_at)
            VALUES (1, ?, ?, datetime('now'))
        """, (INITIAL_CAPITAL, INITIAL_CAPITAL))

        # Paper Trades with comprehensive setup reason
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gold_paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                status TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                units REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                risk_usd REAL NOT NULL,
                exit_time TEXT,
                exit_price REAL,
                exit_reason TEXT,
                pnl_usd REAL,
                r_multiple REAL,
                setup_details TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON gold_paper_trades(status, symbol)")

        # Collector activity log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gold_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                rows_received INTEGER NOT NULL,
                status TEXT NOT NULL,
                message TEXT
            )
        """)

        # Backtest results cache
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gold_backtest_cache (
                id INTEGER PRIMARY KEY CHECK(id=1),
                generated_at TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                trades_json TEXT NOT NULL
            )
        """)
        # Clean up any legacy un-bucketed tick rows with non-zero seconds
        conn.execute("DELETE FROM gold_candles WHERE candle_time NOT LIKE '%:00Z'")

def save_candles(symbol: str, interval: str, candles: List[Dict[str, Any]]) -> int:
    init_db()
    rows = []
    for c in candles:
        rows.append((
            symbol,
            interval,
            c["datetime"],
            float(c["open"]),
            float(c["high"]),
            float(c["low"]),
            float(c["close"]),
            float(c.get("volume", 0.0) or 0.0)
        ))
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany("""
            INSERT INTO gold_candles(symbol, interval, candle_time, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, interval, candle_time) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume
        """, rows)
    return len(rows)

def read_candles(symbol: str, interval: str, limit: int = 500) -> List[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute("""
            SELECT symbol, interval, candle_time AS datetime, open, high, low, close, volume
            FROM gold_candles
            WHERE symbol=? AND interval=?
            ORDER BY candle_time DESC
            LIMIT ?
        """, (symbol, interval, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]

def log_run(symbol: str, interval: str, count: int, status: str, message: str = ""):
    with connect() as conn:
        conn.execute("""
            INSERT INTO gold_runs (symbol, interval, rows_received, status, message)
            VALUES (?, ?, ?, ?, ?)
        """, (symbol, interval, count, status, str(message)[:400]))

def get_latest_runs(status: Optional[str] = None, interval: Optional[str] = None, search: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    query = "SELECT * FROM gold_runs WHERE 1=1"
    args = []
    if status and status.upper() != "ALL":
        query += " AND status = ?"
        args.append(status.upper())
    if interval and interval.upper() != "ALL":
        query += " AND interval = ?"
        args.append(interval)
    if search:
        query += " AND (message LIKE ? OR symbol LIKE ?)"
        args.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        rows = conn.execute(query, args).fetchall()
    return [dict(r) for r in rows]

def get_account() -> Dict[str, Any]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM gold_paper_account WHERE id=1").fetchone()
        return dict(row) if row else {"initial_capital": INITIAL_CAPITAL, "cash_balance": INITIAL_CAPITAL}

def update_account_balance(pnl: float):
    with connect() as conn:
        conn.execute("UPDATE gold_paper_account SET cash_balance = cash_balance + ? WHERE id=1", (pnl,))

def get_paper_trades(status: Optional[str] = None, side: Optional[str] = None, outcome: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None, search: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    init_db()
    query = "SELECT * FROM gold_paper_trades WHERE 1=1"
    args = []
    if status and status.upper() != "ALL":
        query += " AND status = ?"
        args.append(status.upper())
    if side and side.upper() != "ALL":
        query += " AND side = ?"
        args.append(side.upper())
    if outcome and outcome.upper() != "ALL":
        if outcome.upper() == "WIN":
            query += " AND pnl_usd > 0"
        elif outcome.upper() == "LOSS":
            query += " AND pnl_usd <= 0"
    if date_from:
        query += " AND entry_time >= ?"
        args.append(date_from)
    if date_to:
        query += " AND entry_time <= ?"
        args.append(date_to + " 23:59:59")
    if search:
        query += " AND (setup_details LIKE ? OR exit_reason LIKE ? OR symbol LIKE ?)"
        args.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    query += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        rows = conn.execute(query, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("setup_details"):
            try:
                d["setup_details"] = json.loads(d["setup_details"])
            except Exception:
                pass
        out.append(d)
    return out

def save_backtest_cache(metrics: Dict[str, Any], trades: List[Dict[str, Any]], version_key: str = "v2_upgraded"):
    init_db()
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gold_backtest_cache_v2 (
                version_key TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                trades_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO gold_backtest_cache_v2 (version_key, generated_at, metrics_json, trades_json)
            VALUES (?, datetime('now'), ?, ?)
            ON CONFLICT(version_key) DO UPDATE SET
                generated_at=excluded.generated_at,
                metrics_json=excluded.metrics_json,
                trades_json=excluded.trades_json
        """, (version_key, json.dumps(metrics), json.dumps(trades)))

def get_backtest_cache(version_key: str = "v2_upgraded") -> Optional[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gold_backtest_cache_v2 (
                version_key TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                trades_json TEXT NOT NULL
            )
        """)
        # If looking for v1_baseline and not in v2 table, check old table
        row = conn.execute("SELECT * FROM gold_backtest_cache_v2 WHERE version_key=?", (version_key,)).fetchone()
        if not row and version_key == "v1_baseline":
            old_row = conn.execute("SELECT * FROM gold_backtest_cache WHERE id=1").fetchone()
            if old_row:
                # Migrate to v2 table
                conn.execute("""
                    INSERT OR REPLACE INTO gold_backtest_cache_v2 (version_key, generated_at, metrics_json, trades_json)
                    VALUES ('v1_baseline', ?, ?, ?)
                """, (old_row["generated_at"], old_row["metrics_json"], old_row["trades_json"]))
                row = conn.execute("SELECT * FROM gold_backtest_cache_v2 WHERE version_key='v1_baseline'").fetchone()

        if not row:
            # Fallback for old callers
            if version_key == "v1":
                return get_backtest_cache("v1_baseline")
            elif version_key == "v2":
                return get_backtest_cache("v2_upgraded")
            return None

        return {
            "version_key": row["version_key"],
            "generated_at": row["generated_at"],
            "metrics": json.loads(row["metrics_json"]),
            "trades": json.loads(row["trades_json"])
        }
