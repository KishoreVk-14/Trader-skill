# Gold SMC Strategy Monitor & Paper Trading App

An institutional **Smart Money Concepts (SMC)** trading monitor and automated paper trading system dedicated to **Gold (`XAU/USD`)**.

---

## 1. Strategy Overview

This application implements the multi-timeframe ICT / Smart Money institutional rule set:

```
[4H Timeframe]  ──► 1. Macro Trend Confirmation (EMA 50/200 & Swing Highs/Lows Structure)
      │
[15M Timeframe] ──► 2. Intraday Trend Alignment (Must align with 4H bias)
      │
[1H / 4H Zone]  ──► 3. Internal Liquidity Retracement (Price enters & mitigates HTF Bullish/Bearish FVG)
      │
[Benchmark SMT] ──► 4. Reversal with SMT Divergence (Gold vs Silver XAG/USD or DXY)
      │
[5M Timeframe]  ──► 5. 3 Straight Consecutive Candles Displacement & 5M FVG Creation
      │
[EXECUTION]     ──► 6. Entry at 50% Consequent Encroachment (CE) of 5M FVG
                        - Stop Loss: Recent 5M/15M Swing Low/High (with spread buffer)
                        - Target: Recent 5M/15M Draw on Liquidity (DOL / Liquidity Pool)
                        - Minimum Reward:Risk: 1.8R
```

### Institutional Enhancements Added
1. **Session Killzones**: Institutional execution window restricted to **London Open (07:00 – 10:00 UTC)** and **New York AM (12:30 – 15:30 UTC)**. Outside killzones, signals are filtered to protect capital from low-liquidity whipsaws.
2. **SMT Divergence Engine**: Real-time cross-asset swing extrema comparison between Gold (`XAU/USD`) and Silver (`XAG/USD`) to identify institutional liquidity grabs.
3. **Pessimistic Single-Bar Execution**: If both Stop Loss and Take Profit levels fall inside the same 5M candle, the simulation pessimistically assumes the stop was hit first.
4. **Structured Rationale & Audit Trail**: Every trade stores an exact multi-point reasoning chain accessible in the web terminal and interactive charts.

---

## 2. Quick Start & Local Setup

### Installation

```bash
cd d:/TS/gold-monitor
pip install -r requirements.txt
```

### Configuration (`.env`)

Copy `.env.example` to `.env` (already created with default settings). Set `TWELVE_DATA_API_KEY` if you have one.
*(Note: If no API key is provided, the application runs seamlessly using its built-in realistic multi-timeframe Gold market engine).*

### Initialize Database & Seed Market Data

```bash
python -m app.main init-db
```

### Run 1-Year Historical Backtest Simulation

```bash
python -m app.main run-backtest
```

### Start the Modern Web Dashboard

```bash
python -m app.main web --port 8060
```
Open your browser at **`http://127.0.0.1:8060`**.

---

## 3. Features & Pages

* **Market Overview**:
  - Live Gold Spot price & session clock.
  - 4H Macro Trend & 15M Intraday Alignment status.
  - 6-Gate algorithmic checklist with live PASS / WAITING / FILTERED badges.
  - Active execution ticket with 50% CE entry, SL, and Target DOL.
* **Live Chart & Institutional Rationale**:
  - Interactive multi-timeframe chart (5M, 15M, 1H, 4H).
  - Price, EMA 50, EMA 200, and active 5M & 1H Fair Value Gaps.
  - Trade Rationale & Audit Trail callout box detailing every step of the setup.
* **Paper Trading Terminal**:
  - Virtual account balance & equity ($10,000 initial, 1% risk per trade).
  - Realized/Unrealized P&L, Win Rate %, Profit Factor, and Average R-Multiple.
  - Open Positions and Closed Trades tables.
  - Click any trade to inspect on the chart!
* **1-Year Backtest Data Page**:
  - Full 365-day backtest simulation report.
  - Cumulative equity curve chart.
  - Complete trade log with every entry, exit, R-multiple, and the exact step-by-step reason why each trade was taken.
  - Filterable by side (BUY / SELL) and outcome (Wins / Losses).
* **Collector Activity**:
  - System logs of continuous polling cycles.

---

## 4. Continuous Daemons (EC2 / Server Deployment)

Service unit files are provided in `systemd/`:

```bash
sudo cp systemd/gold-collector.service /etc/systemd/system/
sudo cp systemd/gold-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gold-collector gold-dashboard
```
