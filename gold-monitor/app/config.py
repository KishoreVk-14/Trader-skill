import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# API Keys
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

# Database
DB_PATH = os.getenv("GOLD_DB_PATH", str(BASE_DIR / "data" / "gold_smc.db"))
if not os.path.isabs(DB_PATH):
    DB_PATH = str(BASE_DIR / DB_PATH)

# Symbols
GOLD_SYMBOL = os.getenv("GOLD_SYMBOL", "XAU/USD")
BENCHMARK_SYMBOL = os.getenv("BENCHMARK_SYMBOL", "XAG/USD")

# Server
WEB_HOST = os.getenv("GOLD_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("GOLD_WEB_PORT", "8060"))

# Risk & Trading Configuration
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "10000.0"))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0")) / 100.0  # 0.01
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
MAX_LEVERAGE = float(os.getenv("MAX_LEVERAGE", "10.0"))
GOLD_SPREAD_USD = float(os.getenv("GOLD_SPREAD_USD", "0.25"))  # 25 cents spread
SL_BUFFER_ATR_MULT = float(os.getenv("SL_BUFFER_ATR_MULT", "0.3"))
MIN_RR_RATIO = float(os.getenv("MIN_RR_RATIO", "1.8"))

# Sessions / Killzones (UTC)
USE_KILLZONES = os.getenv("USE_KILLZONES", "true").lower() in ("1", "true", "yes")
LONDON_KZ_START = os.getenv("LONDON_KILLZONE_START", "07:00")
LONDON_KZ_END = os.getenv("LONDON_KILLZONE_END", "10:00")
NY_KZ_START = os.getenv("NY_KILLZONE_START", "12:30")
NY_KZ_END = os.getenv("NY_KILLZONE_END", "15:30")
