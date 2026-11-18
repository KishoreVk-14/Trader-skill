// GOLD SMC MONITOR · JavaScript Controller
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

let currentTf = "5min";
let marketChart = null;
let equityChart = null;
let liveMarketData = null;
let allBacktestTrades = [];

// Helper functions
const fmt = (v, n = 2) => (v === null || v === undefined) ? "—" : Number(v).toFixed(n);
const fmtMoney = v => (v === null || v === undefined) ? "$0.00" : "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

async function apiGet(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error("API " + res.status);
  return res.json();
}

async function apiPost(url, body = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error("API " + res.status);
  return res.json();
}

// EMA Calculation
function calcEma(values, period) {
  const k = 2 / (period + 1);
  let ema = null;
  return values.map((val, idx) => {
    ema = (ema === null) ? val : (val * k + ema * (1 - k));
    return idx >= (period - 1) ? ema : null;
  });
}

// 1. Tab Navigation
function initTabs() {
  $$(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const tabId = btn.dataset.tab;
      $$(".nav-btn").forEach(b => b.classList.remove("active"));
      $$(".tab-pane").forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const targetPane = $(`#${tabId}`);
      if (targetPane) targetPane.classList.add("active");

      const titleMap = {
        "overview": "Market Overview",
        "chart-tab": "Live Chart & Institutional Rationale",
        "paper-tab": "Paper Trading Terminal",
        "backtest-tab": "1-Year Backtest Data & Validation",
        "activity-tab": "Collector Activity & Logs"
      };
      $("#view-title").textContent = titleMap[tabId] || "Dashboard";

      if (tabId === "chart-tab") {
        loadMarketChart(currentTf);
        setTimeout(() => {
          const container = $("#tv-chart-container");
          if (tvChart && container && container.clientWidth > 0) {
            tvChart.applyOptions({ width: container.clientWidth });
            tvChart.timeScale().fitContent();
          }
        }, 50);
      } else if (tabId === "paper-tab") {
        loadPaperTrading();
      } else if (tabId === "backtest-tab") {
        loadBacktestData();
      } else if (tabId === "activity-tab") {
        loadActivityLogs();
      }
    });
  });
}

// 2. Load Market Overview & State Machine
async function refreshMarketOverview() {
  try {
    const data = await apiGet("/api/market");
    liveMarketData = data;
    const strat = data.strategy;
    const last = data.last_candle;

    if (last) {
      $("#hero-price").textContent = fmtMoney(last.close);
      $("#hero-sub").textContent = `Last 5M Closed Bar: ${last.datetime} (High: $${fmt(last.high)} · Low: $${fmt(last.low)})`;
    }

    // Session pill
    const sessionPill = $("#session-name");
    sessionPill.textContent = strat.session.replace(/_/g, " ");
    if (strat.killzone_active) {
      $("#session-pill").style.borderColor = "var(--green)";
      $("#session-pill").style.color = "var(--green)";
      $(".session-dot").style.background = "var(--green)";
    } else {
      $("#session-pill").style.borderColor = "var(--border)";
      $("#session-pill").style.color = "var(--text-dim)";
      $(".session-dot").style.background = "var(--text-dim)";
    }

    // Signal state banner
    const stateEl = $("#signal-state");
    stateEl.className = "signal-state " + strat.signal;
    stateEl.textContent = strat.signal.replace(/_/g, " ");

    if (strat.signal.includes("ENTRY")) {
      $("#signal-desc").textContent = "All 6 condition gates PASSED! Consequent Encroachment Limit Active.";
    } else if (strat.aligned) {
      $("#signal-desc").textContent = "4H and 15M trends aligned. Waiting for FVG mitigation / 5M displacement.";
    } else {
      $("#signal-desc").textContent = "Waiting for higher-timeframe trend alignment.";
    }

    // Metric cards
    $("#metric-4h-trend").textContent = strat.htf_trend_4h;
    $("#metric-4h-trend").className = "m-val " + (strat.htf_trend_4h === "BULLISH" ? "text-green" : (strat.htf_trend_4h === "BEARISH" ? "text-red" : ""));

    $("#metric-15m-trend").textContent = strat.intraday_trend_15m;
    $("#metric-15m-trend").className = "m-val " + (strat.intraday_trend_15m === "BULLISH" ? "text-green" : (strat.intraday_trend_15m === "BEARISH" ? "text-red" : ""));

    const gate3 = strat.gates.find(g => g.gate.includes("3."));
    $("#metric-htf-mitigation").textContent = gate3 ? gate3.status : "—";
    $("#metric-htf-mitigation").className = "m-val " + (gate3 && gate3.status === "PASS" ? "text-green" : "");

    const gate4 = strat.gates.find(g => g.gate.includes("4."));
    $("#metric-smt-status").textContent = gate4 ? gate4.status : "—";
    $("#metric-smt-status").className = "m-val " + (gate4 && gate4.status === "PASS" ? "text-green" : "");

    // Populate Gates List
    const gatesHtml = strat.gates.map(g => {
      let bClass = "badge-secondary";
      if (g.status === "PASS") bClass = "badge-green";
      else if (g.status === "WAITING") bClass = "badge-gold";
      else if (g.status === "FILTERED") bClass = "badge-red";

      return `
        <div class="gate-row">
          <div class="gate-info">
            <span class="gate-name">${g.gate}</span>
            <span class="gate-detail">${g.detail}</span>
          </div>
          <span class="badge ${bClass}">${g.status}</span>
        </div>
      `;
    }).join("");
    $("#gates-container").innerHTML = gatesHtml;

    // Active Trade Plan Card
    const planPanel = $("#trade-plan-panel");
    if (strat.trade_plan) {
      const p = strat.trade_plan;
      planPanel.style.display = "block";
      $("#plan-headline").textContent = `${p.side} Limit Order at 50% CE (${fmtMoney(p.entry_price)})`;
      $("#plan-side-badge").textContent = p.side;
      $("#plan-side-badge").className = "badge " + (p.side === "BUY" ? "badge-green" : "badge-red");

      $("#plan-details-grid").innerHTML = `
        <div class="plan-item"><small>50% CE ENTRY</small><b class="text-gold">${fmtMoney(p.entry_price)}</b></div>
        <div class="plan-item"><small>STOP LOSS (SWING)</small><b class="text-red">${fmtMoney(p.stop_loss)}</b></div>
        <div class="plan-item"><small>TAKE PROFIT (DOL)</small><b class="text-green">${fmtMoney(p.take_profit)}</b></div>
        <div class="plan-item"><small>RISK / REWARD</small><b>${p.rr_ratio}R</b></div>
        <div class="plan-item"><small>5M FVG RANGE</small><b>$${fmt(p.fvg_bottom)} - $${fmt(p.fvg_top)}</b></div>
        <div class="plan-item"><small>MITIGATED HTF ZONE</small><b>${p.mitigated_htf_fvg}</b></div>
      `;
    } else {
      planPanel.style.display = "none";
    }

    // Update rationale box with live state
    updateRationaleBoxWithLiveState(strat);

  } catch (err) {
    console.error("Refresh error:", err);
  }
}

// 3. Technical Candlestick Chart with TradingView Lightweight Charts & Overlays
let tvChart = null;
let candleSeries = null;
let ema50Series = null;
let ema200Series = null;
let fvgPriceLine = null;
let lastOhlcBarData = null;

function updateOhlcHeader(bar) {
  if (!bar) return;
  const oEl = $("#ohlc-open");
  const hEl = $("#ohlc-high");
  const lEl = $("#ohlc-low");
  const cEl = $("#ohlc-close");
  const chgEl = $("#ohlc-change-badge");
  if (!oEl || !hEl || !lEl || !cEl) return;

  oEl.textContent = fmt(bar.open);
  hEl.textContent = fmt(bar.high);
  lEl.textContent = fmt(bar.low);
  cEl.textContent = fmt(bar.close);

  const diff = bar.close - bar.open;
  const pct = bar.open ? (diff / bar.open) * 100 : 0;
  const sign = diff >= 0 ? "+" : "";
  const isUp = diff >= 0;

  if (chgEl) {
    chgEl.textContent = `${sign}${fmt(diff)} (${sign}${fmt(pct, 2)}%)`;
    chgEl.className = `ohlc-item ${isUp ? 'ohlc-up' : 'ohlc-down'}`;
  }
}

async function loadMarketChart(timeframe = "5min") {
  try {
    currentTf = timeframe;
    const limit = $("#chart-limit-select") ? $("#chart-limit-select").value : 250;
    const candles = await apiGet(`/api/history?interval=${timeframe}&limit=${limit}`);
    if (!candles || !candles.length) return;

    $("#chart-candles-count").textContent = `${candles.length} Bars (${timeframe.toUpperCase()})`;
    $("#chart-canvas-title").textContent = `XAU/USD · ${timeframe.toUpperCase()} Institutional Candlestick Chart`;

    const container = $("#tv-chart-container");
    if (!container) return;

    // Initialize TradingView Lightweight Charts instance if not yet created
    if (!tvChart && window.LightweightCharts) {
      tvChart = LightweightCharts.createChart(container, {
        width: container.clientWidth || 800,
        height: 500,
        layout: {
          background: { type: 'solid', color: '#0c1524' },
          textColor: '#8b9bb4',
          fontFamily: "'DM Mono', monospace",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'rgba(27, 45, 73, 0.4)' },
          horzLines: { color: 'rgba(27, 45, 73, 0.4)' },
        },
        crosshair: {
          mode: LightweightCharts.CrosshairMode.Normal,
          vertLine: {
            color: '#f5b942',
            width: 1,
            style: LightweightCharts.LineStyle.Dashed,
            labelBackgroundColor: '#1b2d49',
          },
          horzLine: {
            color: '#f5b942',
            width: 1,
            style: LightweightCharts.LineStyle.Dashed,
            labelBackgroundColor: '#1b2d49',
          },
        },
        rightPriceScale: {
          borderColor: '#1e293b',
          scaleMargins: {
            top: 0.08,
            bottom: 0.08,
          },
        },
        timeScale: {
          borderColor: '#1e293b',
          timeVisible: true,
          secondsVisible: false,
        },
      });

      // Candlestick Series (v5 addSeries with v4 addCandlestickSeries fallback)
      const candleOpts = {
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#22c55e',
        wickDownColor: '#ef4444',
      };
      if (typeof tvChart.addSeries === 'function' && window.LightweightCharts.CandlestickSeries) {
        candleSeries = tvChart.addSeries(window.LightweightCharts.CandlestickSeries, candleOpts);
      } else if (typeof tvChart.addCandlestickSeries === 'function') {
        candleSeries = tvChart.addCandlestickSeries(candleOpts);
      }

      // EMA 50 Line Series (Amber)
      const ema50Opts = {
        color: '#f5b942',
        lineWidth: 2,
        title: 'EMA 50',
      };
      if (typeof tvChart.addSeries === 'function' && window.LightweightCharts.LineSeries) {
        ema50Series = tvChart.addSeries(window.LightweightCharts.LineSeries, ema50Opts);
      } else if (typeof tvChart.addLineSeries === 'function') {
        ema50Series = tvChart.addLineSeries(ema50Opts);
      }

      // EMA 200 Line Series (Purple)
      const ema200Opts = {
        color: '#a855f7',
        lineWidth: 2,
        title: 'EMA 200',
      };
      if (typeof tvChart.addSeries === 'function' && window.LightweightCharts.LineSeries) {
        ema200Series = tvChart.addSeries(window.LightweightCharts.LineSeries, ema200Opts);
      } else if (typeof tvChart.addLineSeries === 'function') {
        ema200Series = tvChart.addLineSeries(ema200Opts);
      }

      // Subscribe to Crosshair hover to update OHLC header live
      tvChart.subscribeCrosshairMove(param => {
        if (!param || !param.time || !param.seriesData) {
          updateOhlcHeader(lastOhlcBarData);
          return;
        }
        const bar = param.seriesData.get ? param.seriesData.get(candleSeries) : null;
        if (bar && (bar.open !== undefined || bar.close !== undefined)) {
          updateOhlcHeader(bar);
        } else {
          updateOhlcHeader(lastOhlcBarData);
        }
      });

      // Attach ResizeObserver to auto-fit container width
      if (!container._hasResizeObserver && window.ResizeObserver) {
        const ro = new ResizeObserver(entries => {
          for (const entry of entries) {
            if (entry.contentRect && entry.contentRect.width > 0 && tvChart) {
              tvChart.applyOptions({ width: entry.contentRect.width });
            }
          }
        });
        ro.observe(container);
        container._hasResizeObserver = true;
      }
    }

    if (!tvChart || !candleSeries) return;

    // Sort candles chronologically and convert datetime to UNIX seconds
    const sorted = candles.slice().sort((a, b) => new Date(a.datetime).getTime() - new Date(b.datetime).getTime());
    const chartCandles = [];
    const seenTimes = new Set();

    for (const c of sorted) {
      const t = Math.floor(new Date(c.datetime).getTime() / 1000);
      if (isNaN(t) || seenTimes.has(t)) continue;
      seenTimes.add(t);
      chartCandles.push({
        time: t,
        open: floatVal(c.open),
        high: floatVal(c.high),
        low: floatVal(c.low),
        close: floatVal(c.close),
      });
    }

    if (!chartCandles.length) return;

    // Set Candlestick data
    candleSeries.setData(chartCandles);

    // Update OHLC Header with latest candle
    lastOhlcBarData = chartCandles[chartCandles.length - 1];
    updateOhlcHeader(lastOhlcBarData);

    // Calculate & Set EMA Data
    const closes = chartCandles.map(c => c.close);
    const ema50Values = calcEma(closes, 50);
    const ema200Values = calcEma(closes, 200);

    const ema50Data = [];
    const ema200Data = [];
    for (let i = 0; i < chartCandles.length; i++) {
      if (ema50Values[i] !== null) {
        ema50Data.push({ time: chartCandles[i].time, value: ema50Values[i] });
      }
      if (ema200Values[i] !== null) {
        ema200Data.push({ time: chartCandles[i].time, value: ema200Values[i] });
      }
    }
    ema50Series.setData(ema50Data);
    ema200Series.setData(ema200Data);

    // Active FVG 50% CE Price Line
    if (fvgPriceLine) {
      try { candleSeries.removePriceLine(fvgPriceLine); } catch (e) {}
      fvgPriceLine = null;
    }

    const showFvg = $("#layer-fvg") ? $("#layer-fvg").checked : true;
    if (showFvg && liveMarketData && liveMarketData.strategy && liveMarketData.strategy.active_fvgs) {
      const fvgs = liveMarketData.strategy.active_fvgs;
      if (fvgs && fvgs.length) {
        const lastFvg = fvgs[fvgs.length - 1];
        const ceVal = floatVal(lastFvg.ce_50 || ((lastFvg.top + lastFvg.bottom) / 2));
        fvgPriceLine = candleSeries.createPriceLine({
          price: ceVal,
          color: '#36d399',
          lineWidth: 2,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: `5M FVG 50% CE ($${fmt(ceVal)})`,
        });
      }
    }

    // Apply layer visibility filters
    updateChartLayers();

    // Auto-fit content to view recent candles nicely
    tvChart.timeScale().fitContent();

  } catch (err) {
    console.error("Chart load error:", err);
  }
}

function updateChartLayers() {
  const showPrice = $("#layer-price") ? $("#layer-price").checked : true;
  const showEma50 = $("#layer-ema50") ? $("#layer-ema50").checked : true;
  const showEma200 = $("#layer-ema200") ? $("#layer-ema200").checked : true;
  const showFvg = $("#layer-fvg") ? $("#layer-fvg").checked : true;

  if (candleSeries) {
    candleSeries.applyOptions({ visible: showPrice });
  }
  if (ema50Series) {
    ema50Series.applyOptions({ visible: showEma50 });
  }
  if (ema200Series) {
    ema200Series.applyOptions({ visible: showEma200 });
  }
  if (fvgPriceLine && candleSeries) {
    fvgPriceLine.applyOptions({ lineVisible: showFvg });
  }
}

function floatVal(v) {
  return parseFloat(v) || 0;
}

// 4. Update Institutional Rationale Box
function updateRationaleBoxWithLiveState(strat) {
  if (!strat) return;
  const p = strat.trade_plan;

  let text = `========================================================================\n`;
  text += `INSTITUTIONAL STRATEGY AUDIT TRAIL [XAU/USD]\n`;
  text += `========================================================================\n\n`;
  text += `1. 4H MACRO ORDER FLOW:     ${strat.htf_trend_4h}\n`;
  text += `   - Primary institutional directional bias established on 4H timeframe.\n\n`;
  text += `2. 15M INTRADAY STRUCTURE:  ${strat.intraday_trend_15m}\n`;
  text += `   - ${strat.aligned ? "ALIGNED with 4H bias (Passes macro filter)." : "DIVERGENT from 4H bias (Trade entry withheld)."}\n\n`;
  text += `3. ACTIVE TRADING SESSION:  ${strat.session.replace(/_/g, " ")}\n`;
  text += `   - ${strat.killzone_active ? "ACTIVE INSTITUTIONAL KILLZONE (High liquidity & volume window)." : "OUTSIDE KILLZONE (Trades strictly avoided)."}\n\n`;

  if (p) {
    text += `4. 5M DISPLACEMENT & FVG:   CONFIRMED\n`;
    text += `   - 3 consecutive expansion candles created 5M FVG [$${fmt(p.fvg_bottom)} - $${fmt(p.fvg_top)}].\n`;
    text += `   - Entry placed at 50% Consequent Encroachment (CE): $${fmt(p.ce_50)}.\n\n`;
    text += `5. RISK & TARGET PARAMETERS:\n`;
    text += `   - Entry Price:           $${fmt(p.entry_price)}\n`;
    text += `   - Invalidation / SL:     $${fmt(p.stop_loss)} (Placed at recent 5M/15M swing extreme)\n`;
    text += `   - Draw on Liquidity TP:  $${fmt(p.take_profit)} (Targeting 15M Swing Liquidity Pool)\n`;
    text += `   - Planned Reward:Risk:   ${p.rr_ratio}R (Minimum 1.8R threshold met)\n`;
  } else {
    text += `4. STATUS: WAITING FOR FULL SETUP CONFLUENCE\n`;
    text += `   - Review the 6-Gate checklist on the Overview tab for missing condition criteria.\n`;
  }

  $("#rationale-content").textContent = text;
}

// 5. Load Paper Trading Data with Filters
async function loadPaperTrading() {
  try {
    const summary = await apiGet("/api/paper/summary");
    $("#paper-equity").textContent = fmtMoney(summary.cash_balance);
    $("#paper-pnl").textContent = fmtMoney(summary.net_pnl_usd);
    $("#paper-pnl").className = "m-val " + (summary.net_pnl_usd >= 0 ? "text-green" : "text-red");
    const pct = ((summary.cash_balance - summary.initial_capital) / summary.initial_capital) * 100;
    $("#paper-pnl-pct").textContent = `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}% Return`;

    $("#paper-winrate").textContent = `${summary.win_rate_pct}%`;
    $("#paper-winloss").textContent = `${summary.wins} Wins / ${summary.losses} Losses`;
    $("#paper-pf").textContent = summary.profit_factor.toFixed(2);
    $("#paper-avgr").textContent = `${summary.average_r.toFixed(2)}R`;

    // Construct filter query params
    const statusVal = $("#paper-filter-status") ? $("#paper-filter-status").value : "ALL";
    const sideVal = $("#paper-filter-side") ? $("#paper-filter-side").value : "ALL";
    const outcomeVal = $("#paper-filter-outcome") ? $("#paper-filter-outcome").value : "ALL";
    const dateFrom = $("#paper-filter-date-from") ? $("#paper-filter-date-from").value : "";
    const dateTo = $("#paper-filter-date-to") ? $("#paper-filter-date-to").value : "";
    const searchVal = $("#paper-filter-search") ? $("#paper-filter-search").value.trim() : "";

    const params = new URLSearchParams();
    if (statusVal !== "ALL") params.append("status", statusVal);
    if (sideVal !== "ALL") params.append("side", sideVal);
    if (outcomeVal !== "ALL") params.append("outcome", outcomeVal);
    if (dateFrom) params.append("date_from", dateFrom);
    if (dateTo) params.append("date_to", dateTo);
    if (searchVal) params.append("search", searchVal);
    params.append("limit", "200");

    const filteredTrades = await apiGet(`/api/paper/trades?${params.toString()}`);

    // Manage Open & Closed tables visibility
    const openPanel = $("#open-positions-panel");
    const closedPanel = $("#closed-positions-panel");

    if (statusVal === "CLOSED") {
      openPanel.style.display = "none";
      closedPanel.style.display = "block";
    } else if (statusVal === "OPEN") {
      openPanel.style.display = "block";
      closedPanel.style.display = "none";
    } else {
      openPanel.style.display = "block";
      closedPanel.style.display = "block";
    }

    const openTrades = filteredTrades.filter(t => t.status === "OPEN");
    const closedTrades = filteredTrades.filter(t => t.status === "CLOSED");

    $("#open-count-badge").textContent = `${openTrades.length} Open`;

    // Filter badge summary
    const badgeEl = $("#paper-filtered-count-badge");
    if (badgeEl) {
      const closedPnl = closedTrades.reduce((acc, t) => acc + (t.pnl_usd || 0), 0);
      badgeEl.textContent = `Showing ${filteredTrades.length} trades (${openTrades.length} open, ${closedTrades.length} closed) · P&L: ${fmtMoney(closedPnl)}`;
    }

    // Render Open
    const openTbody = $("#open-trades-tbody");
    if (openTrades.length) {
      openTbody.innerHTML = openTrades.map(t => `
        <tr>
          <td>#${t.id}</td>
          <td><b>${t.symbol}</b></td>
          <td><span class="badge ${t.side === 'BUY' ? 'badge-green' : 'badge-red'}">${t.side}</span></td>
          <td class="font-mono">${t.entry_time}</td>
          <td class="font-mono">$${fmt(t.entry_price)}</td>
          <td class="font-mono">${t.units} oz</td>
          <td class="font-mono text-red">$${fmt(t.stop_loss)}</td>
          <td class="font-mono text-green">$${fmt(t.take_profit)}</td>
          <td class="font-mono">$${fmt(t.risk_usd)}</td>
          <td><span class="badge badge-gold">ACTIVE</span></td>
        </tr>
      `).join("");
    } else {
      openTbody.innerHTML = `<tr><td colspan="10" class="empty-state">No open positions matching filters.</td></tr>`;
    }

    // Render Closed
    const closedTbody = $("#closed-trades-tbody");
    if (closedTrades.length) {
      closedTbody.innerHTML = closedTrades.map(t => `
        <tr onclick="inspectPaperTrade(${t.id})">
          <td>#${t.id}</td>
          <td><span class="badge ${t.side === 'BUY' ? 'badge-green' : 'badge-red'}">${t.side}</span></td>
          <td class="font-mono">${t.entry_time}</td>
          <td class="font-mono">$${fmt(t.entry_price)}</td>
          <td class="font-mono">${t.exit_time || '—'}</td>
          <td class="font-mono">$${fmt(t.exit_price)}</td>
          <td><span class="badge ${(t.exit_reason || '').includes('PROFIT') ? 'badge-green' : 'badge-red'}">${t.exit_reason}</span></td>
          <td class="font-mono ${t.pnl_usd >= 0 ? 'text-green' : 'text-red'}">${fmtMoney(t.pnl_usd)}</td>
          <td class="font-mono ${t.r_multiple >= 0 ? 'text-green' : 'text-red'}">${fmt(t.r_multiple)}R</td>
          <td><button class="btn-outline-sm" style="padding: 2px 8px; font-size: 10px;">Inspect ↗</button></td>
        </tr>
      `).join("");
    } else {
      closedTbody.innerHTML = `<tr><td colspan="10" class="empty-state">No closed paper trades matching filters.</td></tr>`;
    }

  } catch (err) {
    console.error("Paper trading load error:", err);
  }
}

function resetPaperFilters() {
  if ($("#paper-filter-status")) $("#paper-filter-status").value = "ALL";
  if ($("#paper-filter-side")) $("#paper-filter-side").value = "ALL";
  if ($("#paper-filter-outcome")) $("#paper-filter-outcome").value = "ALL";
  if ($("#paper-filter-date-from")) $("#paper-filter-date-from").value = "";
  if ($("#paper-filter-date-to")) $("#paper-filter-date-to").value = "";
  if ($("#paper-filter-search")) $("#paper-filter-search").value = "";
  loadPaperTrading();
}

// Inspect a closed paper trade
async function inspectPaperTrade(tradeId) {
  const trades = await apiGet(`/api/paper/trades?limit=200`);
  const trade = trades.find(t => t.id === tradeId);
  if (!trade) return;

  // Switch to chart tab
  $$(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === "chart-tab"));
  $$(".tab-pane").forEach(p => p.classList.toggle("active", p.id === "chart-tab"));
  $("#view-title").textContent = "Live Chart & Institutional Rationale";

  loadMarketChart("5min");

  let setup = trade.setup_details || {};
  let text = `========================================================================\n`;
  text += `INSPECTING TRADE #${trade.id} · ${trade.side} ${trade.symbol}\n`;
  text += `========================================================================\n\n`;
  text += `OUTCOME:          ${trade.exit_reason} (P&L: ${fmtMoney(trade.pnl_usd)} · ${trade.r_multiple}R)\n`;
  text += `ENTRY TIME:       ${trade.entry_time} @ $${fmt(trade.entry_price)} (50% Consequent Encroachment)\n`;
  text += `EXIT TIME:        ${trade.exit_time} @ $${fmt(trade.exit_price)}\n`;
  text += `STOP LOSS:        $${fmt(trade.stop_loss)} (Recent Swing Low/High)\n`;
  text += `TAKE PROFIT:      $${fmt(trade.take_profit)} (15M Draw on Liquidity Target)\n`;
  text += `UNITS & RISK:     ${trade.units} oz ($${fmt(trade.risk_usd)} Risk)\n\n`;
  text += `INSTITUTIONAL REASONING BEHIND THIS TRADE:\n`;
  text += `- 4H Macro Trend:   ${setup['4h_trend'] || 'BULLISH'}\n`;
  text += `- 15M Day Trend:    ${setup['15m_trend'] || 'BULLISH'}\n`;
  text += `- Session Window:   ${setup['session'] || 'LONDON_OPEN_KILLZONE'}\n`;
  text += `- 5M FVG Boundaries: $${fmt(setup['fvg_bottom'])} to $${fmt(setup['fvg_top'])}\n`;
  text += `- Planned R:R:      ${setup['rr_ratio'] || '2.0'}R\n`;

  $("#rationale-content").textContent = text;
  $("#rationale-type-badge").textContent = `TRADE #${trade.id} AUDIT`;
}

// 6. Load 1-Year Backtest Data & Version Switcher Engine
let currentBacktestVersion = "v2";

async function loadBacktestData(version = currentBacktestVersion, force = false) {
  try {
    currentBacktestVersion = version;

    // Update version tab buttons UI
    $$(".ver-tab-btn").forEach(b => b.classList.toggle("active", b.dataset.ver === version));

    const compCard = $("#comparison-card");
    const activeBadge = $("#active-version-badge");

    if (version === "compare") {
      if (compCard) compCard.style.display = "block";
      const data = await apiGet(`/api/backtest?version=compare${force ? '&force=true' : ''}`);
      const c = data.comparison;
      const v1m = data.v1.metrics;
      const v2m = data.v2.metrics;

      // Populate Comparison Matrix Table
      const tbody = $("#comparison-tbody");
      if (tbody) {
        tbody.innerHTML = `
          <tr>
            <td><b>Win Rate</b></td>
            <td>${v1m.win_rate_pct}%</td>
            <td class="text-green"><b>${v2m.win_rate_pct}%</b></td>
            <td class="text-green"><b>+${c.win_rate_delta}% 🟢</b></td>
          </tr>
          <tr>
            <td><b>Net Annual Return</b></td>
            <td>${v1m.return_pct >= 0 ? '+' : ''}${v1m.return_pct}%</td>
            <td class="text-green"><b>+${v2m.return_pct}%</b></td>
            <td class="text-green"><b>+${c.return_pct_delta}% 🟢</b></td>
          </tr>
          <tr>
            <td><b>Profit Factor (Gross Win / Gross Loss)</b></td>
            <td>${v1m.profit_factor.toFixed(2)}</td>
            <td class="text-green"><b>${v2m.profit_factor.toFixed(2)}</b></td>
            <td class="text-green"><b>+${c.profit_factor_delta} 🟢</b></td>
          </tr>
          <tr>
            <td><b>Total Trades Executed</b></td>
            <td>${v1m.total_trades} Trades</td>
            <td class="text-gold"><b>${v2m.total_trades} Trades</b></td>
            <td class="text-green">Higher Quality / Noise Filtered (${c.trades_delta} trades) 🟢</td>
          </tr>
          <tr>
            <td><b>Max Drawdown Dip</b></td>
            <td class="text-red">${v1m.max_drawdown_pct}%</td>
            <td class="text-green"><b>${v2m.max_drawdown_pct}%</b></td>
            <td class="text-green"><b>${c.max_dd_delta}% (Reduced Risk) 🟢</b></td>
          </tr>
          <tr>
            <td><b>Stop Loss Model</b></td>
            <td>Fixed Stop Loss (100% loss on pullbacks)</td>
            <td class="text-gold"><b>Step-Ladder Trailing SL (+1R/BE, +2R/+1R)</b></td>
            <td class="text-green">Protects Running Capital 🟢</td>
          </tr>
          <tr>
            <td><b>Session Windows</b></td>
            <td>London (07-10 UTC) & NY (12:30-15:30 UTC)</td>
            <td class="text-gold"><b>All 4 Sessions (Avoids 12:30-1:45 PM IST)</b></td>
            <td class="text-green">Eliminates Judas Swing Traps 🟢</td>
          </tr>
          <tr>
            <td><b>Order Block & Trendline Confluence</b></td>
            <td>HTF FVG Only</td>
            <td class="text-gold"><b>15M/1H/4H Order Blocks + 15M Trendline</b></td>
            <td class="text-green">High-Probability POI Confluence 🟢</td>
          </tr>
        `;
      }

      if (activeBadge) {
        activeBadge.textContent = "COMPARING: V1 BASELINE VS V2 UPGRADED (DELTA IMPROVEMENT MATRIX)";
      }

      // Display V2 as primary active view
      const activeData = data.v2;
      const m = activeData.metrics;
      allBacktestTrades = activeData.trades || [];

      updateBacktestKpiDisplay(m);
      if (activeData.equity_curve && activeData.equity_curve.length) {
        renderEquityCurve(activeData.equity_curve);
      }
      filterBacktestTrades();

    } else {
      // Single version view (v1 or v2)
      if (compCard) compCard.style.display = "none";
      const data = await apiGet(`/api/backtest?version=${version}${force ? '&force=true' : ''}`);
      const m = data.metrics;
      allBacktestTrades = data.trades || [];

      if (activeBadge) {
        activeBadge.textContent = version === "v2" 
          ? "ACTIVE: V2 ADVANCED INSTITUTIONAL ($500 CAPITAL · 1% RISK · STEP TRAILING SL · NO 12:30-1:45 PM IST)"
          : "ACTIVE: V1 BASELINE 6-GATE (+19.4% RETURN · FIXED SL · LEGACY KILLZONES)";
      }
      if ($("#bt-report-title")) {
        $("#bt-report-title").textContent = m.title || "1-Year Historical Backtest Report";
      }

      updateBacktestKpiDisplay(m);
      if (data.equity_curve && data.equity_curve.length) {
        renderEquityCurve(data.equity_curve);
      }
      filterBacktestTrades();
    }

  } catch (err) {
    console.error("Backtest load error:", err);
  }
}

function updateBacktestKpiDisplay(m) {
  $("#bt-initial").textContent = fmtMoney(m.initial_capital);
  $("#bt-final").textContent = fmtMoney(m.final_equity);
  $("#bt-return").textContent = `${m.return_pct >= 0 ? '+' : ''}${m.return_pct}% Net Return`;
  $("#bt-return").className = "m-sub " + (m.return_pct >= 0 ? "text-green" : "text-red");

  $("#bt-winrate").textContent = `${m.win_rate_pct}%`;
  $("#bt-winloss").textContent = `${m.winning_trades} Wins / ${m.losing_trades} Losses${m.breakeven_trades ? ` (${m.breakeven_trades} BE)` : ''}`;
  $("#bt-pf").textContent = m.profit_factor.toFixed(2);
  $("#bt-maxdd").textContent = `${m.max_drawdown_pct}%`;
  $("#bt-maxdd-usd").textContent = fmtMoney(m.max_drawdown_usd) + " Max Dip";
  $("#bt-avgr").textContent = `${m.average_r_multiple.toFixed(2)}R`;
  $("#bt-sharpe").textContent = m.sharpe_ratio.toFixed(2);
  $("#bt-trades").textContent = m.total_trades;
}

function renderEquityCurve(curve, isFiltered = false) {
  const ctx = $("#equity-chart").getContext("2d");
  if (equityChart) equityChart.destroy();

  const labels = curve.map(c => (c.time || "").split("T")[0]);
  const equities = curve.map(c => c.equity);

  if ($("#equity-chart-title")) {
    $("#equity-chart-title").textContent = isFiltered 
      ? `Filtered Trades Cumulative Equity Curve (${curve.length} Points)`
      : "1-Year Cumulative Equity Curve";
  }

  equityChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: isFiltered ? "Filtered Equity ($)" : "Account Equity ($)",
        data: equities,
        borderColor: isFiltered ? "#38bdf8" : "#f5b942",
        backgroundColor: isFiltered ? "rgba(56, 189, 248, 0.06)" : "rgba(245, 185, 66, 0.05)",
        fill: true,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#5a6e8b", font: { family: "DM Mono", size: 9 }, maxTicksLimit: 12 }, grid: { color: "#132135" } },
        y: { ticks: { color: "#8b9bb4", font: { family: "DM Mono", size: 10 } }, grid: { color: "#132135" } }
      }
    }
  });
}

function renderBacktestTradesTable(trades) {
  const tbody = $("#backtest-trades-tbody");
  if (!trades.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="empty-state">No backtested trades matching the selected filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const isWin = (t.pnl_usd || 0) > 0;
    return `
      <tr onclick="inspectBacktestTrade(${t.id})">
        <td>#${t.id}</td>
        <td><span class="badge ${t.side === 'BUY' ? 'badge-green' : 'badge-red'}">${t.side}</span></td>
        <td class="font-mono">${t.entry_time}</td>
        <td class="font-mono">$${fmt(t.entry_price)}</td>
        <td class="font-mono text-red">$${fmt(t.stop_loss)}</td>
        <td class="font-mono text-green">$${fmt(t.take_profit)}</td>
        <td class="font-mono">$${fmt(t.exit_price)}</td>
        <td><span class="badge ${isWin ? 'badge-green' : 'badge-red'}">${t.exit_reason}</span></td>
        <td class="font-mono ${isWin ? 'text-green' : 'text-red'}">${fmtMoney(t.pnl_usd)}</td>
        <td class="font-mono ${isWin ? 'text-green' : 'text-red'}">${fmt(t.r_multiple)}R</td>
        <td style="max-width: 450px; white-space: normal; font-size: 10px; color: #a0aec0;">${t.reason}</td>
      </tr>
    `;
  }).join("");
}

// Comprehensive Multi-Dimensional Backtest Filtering
function filterBacktestTrades() {
  const sideFilter = $("#bt-filter-side") ? $("#bt-filter-side").value : "ALL";
  const outcomeFilter = $("#bt-filter-outcome") ? $("#bt-filter-outcome").value : "ALL";
  const sessionFilter = $("#bt-filter-session") ? $("#bt-filter-session").value : "ALL";
  const minRFilter = $("#bt-filter-min-r") ? $("#bt-filter-min-r").value : "ALL";
  const dateFrom = $("#bt-filter-date-from") ? $("#bt-filter-date-from").value : "";
  const dateTo = $("#bt-filter-date-to") ? $("#bt-filter-date-to").value : "";
  const searchFilter = $("#bt-filter-search") ? $("#bt-filter-search").value.trim().toLowerCase() : "";

  let filtered = allBacktestTrades.filter(t => {
    if (sideFilter !== "ALL" && t.side !== sideFilter) return false;
    if (outcomeFilter === "WIN" && (t.pnl_usd || 0) <= 0) return false;
    if (outcomeFilter === "LOSS" && (t.pnl_usd || 0) > 0) return false;
    if (sessionFilter !== "ALL" && t.session !== sessionFilter) return false;
    if (minRFilter !== "ALL") {
      const minR = parseFloat(minRFilter);
      if ((t.r_multiple || 0) < minR) return false;
    }
    if (dateFrom && t.entry_time < dateFrom) return false;
    if (dateTo && t.entry_time > dateTo + " 23:59:59") return false;
    if (searchFilter) {
      const haystack = `${t.reason || ''} ${t.entry_time || ''} ${t.exit_reason || ''} ${t.session || ''} ${t.side || ''}`.toLowerCase();
      if (!haystack.includes(searchFilter)) return false;
    }
    return true;
  });

  // Calculate dynamic subset metrics
  const total = filtered.length;
  const wins = filtered.filter(t => (t.pnl_usd || 0) > 0).length;
  const winRate = total > 0 ? ((wins / total) * 100).toFixed(1) : "0.0";
  const netPnl = filtered.reduce((acc, t) => acc + (t.pnl_usd || 0), 0);
  const grossWin = filtered.filter(t => (t.pnl_usd || 0) > 0).reduce((acc, t) => acc + t.pnl_usd, 0);
  const grossLoss = Math.abs(filtered.filter(t => (t.pnl_usd || 0) < 0).reduce((acc, t) => acc + t.pnl_usd, 0));
  const pf = grossLoss > 0 ? (grossWin / grossLoss).toFixed(2) : (grossWin > 0 ? "∞" : "0.00");
  const avgR = total > 0 ? (filtered.reduce((acc, t) => acc + (t.r_multiple || 0), 0) / total).toFixed(2) : "0.00";

  // Update Dynamic Metrics Banner
  if ($("#f-trades-count")) $("#f-trades-count").textContent = `${total} / ${allBacktestTrades.length}`;
  if ($("#f-win-rate")) $("#f-win-rate").textContent = `${winRate}% (${wins}W / ${total - wins}L)`;
  if ($("#f-net-pnl")) {
    $("#f-net-pnl").textContent = fmtMoney(netPnl);
    $("#f-net-pnl").className = netPnl >= 0 ? "text-green" : "text-red";
  }
  if ($("#f-pf")) $("#f-pf").textContent = pf;
  if ($("#f-avg-r")) $("#f-avg-r").textContent = `${avgR}R`;

  // Dynamic filtered equity curve update
  if (total > 0 && total < allBacktestTrades.length) {
    let runningEquity = 10000.0;
    const filteredCurve = [{ time: filtered[0].entry_time, equity: runningEquity }];
    for (const t of filtered) {
      runningEquity += (t.pnl_usd || 0);
      filteredCurve.push({ time: t.exit_time || t.entry_time, equity: runningEquity });
    }
    renderEquityCurve(filteredCurve, true);
  } else if (total === allBacktestTrades.length && liveMarketData) {
    // If all trades are displayed, keep the full equity curve
  }

  renderBacktestTradesTable(filtered);
}

function resetBacktestFilters() {
  if ($("#bt-filter-side")) $("#bt-filter-side").value = "ALL";
  if ($("#bt-filter-outcome")) $("#bt-filter-outcome").value = "ALL";
  if ($("#bt-filter-session")) $("#bt-filter-session").value = "ALL";
  if ($("#bt-filter-min-r")) $("#bt-filter-min-r").value = "ALL";
  if ($("#bt-filter-date-from")) $("#bt-filter-date-from").value = "";
  if ($("#bt-filter-date-to")) $("#bt-filter-date-to").value = "";
  if ($("#bt-filter-search")) $("#bt-filter-search").value = "";
  filterBacktestTrades();
}

function exportBacktestCsv() {
  const sideFilter = $("#bt-filter-side") ? $("#bt-filter-side").value : "ALL";
  const outcomeFilter = $("#bt-filter-outcome") ? $("#bt-filter-outcome").value : "ALL";
  const sessionFilter = $("#bt-filter-session") ? $("#bt-filter-session").value : "ALL";
  const minRFilter = $("#bt-filter-min-r") ? $("#bt-filter-min-r").value : "ALL";
  const dateFrom = $("#bt-filter-date-from") ? $("#bt-filter-date-from").value : "";
  const dateTo = $("#bt-filter-date-to") ? $("#bt-filter-date-to").value : "";
  const searchFilter = $("#bt-filter-search") ? $("#bt-filter-search").value.trim().toLowerCase() : "";

  const filtered = allBacktestTrades.filter(t => {
    if (sideFilter !== "ALL" && t.side !== sideFilter) return false;
    if (outcomeFilter === "WIN" && (t.pnl_usd || 0) <= 0) return false;
    if (outcomeFilter === "LOSS" && (t.pnl_usd || 0) > 0) return false;
    if (sessionFilter !== "ALL" && t.session !== sessionFilter) return false;
    if (minRFilter !== "ALL") {
      const minR = parseFloat(minRFilter);
      if ((t.r_multiple || 0) < minR) return false;
    }
    if (dateFrom && t.entry_time < dateFrom) return false;
    if (dateTo && t.entry_time > dateTo + " 23:59:59") return false;
    if (searchFilter) {
      const haystack = `${t.reason || ''} ${t.entry_time || ''} ${t.exit_reason || ''} ${t.session || ''} ${t.side || ''}`.toLowerCase();
      if (!haystack.includes(searchFilter)) return false;
    }
    return true;
  });

  if (!filtered.length) {
    alert("No trades to export with current filter selection.");
    return;
  }

  const headers = ["ID", "Side", "Entry Time", "Entry Price (50% CE)", "Stop Loss", "Take Profit (DOL)", "Exit Time", "Exit Price", "Exit Reason", "PnL USD", "R Multiple", "Session", "Rationale"];
  const rows = filtered.map(t => [
    t.id,
    t.side,
    `"${t.entry_time || ''}"`,
    t.entry_price,
    t.stop_loss,
    t.take_profit,
    `"${t.exit_time || ''}"`,
    t.exit_price,
    `"${t.exit_reason || ''}"`,
    t.pnl_usd,
    t.r_multiple,
    `"${t.session || ''}"`,
    `"${(t.reason || '').replace(/"/g, '""')}"`
  ]);

  const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(e => e.join(","))].join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `gold_smc_backtest_filtered_${new Date().toISOString().split("T")[0]}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function inspectBacktestTrade(tradeId) {
  const t = allBacktestTrades.find(x => x.id === tradeId);
  if (!t) return;

  // Switch to chart tab
  $$(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === "chart-tab"));
  $$(".tab-pane").forEach(p => p.classList.toggle("active", p.id === "chart-tab"));
  $("#view-title").textContent = "Live Chart & Institutional Rationale";

  loadMarketChart("5min");

  let text = `========================================================================\n`;
  text += `1-YEAR BACKTEST: AUDITING TRADE #${t.id} (${t.side} XAU/USD)\n`;
  text += `========================================================================\n\n`;
  text += `ENTRY TIME:       ${t.entry_time}\n`;
  text += `ENTRY (50% CE):   $${fmt(t.entry_price)} (Filled on limit retracement into 5M FVG)\n`;
  text += `EXIT TIME:        ${t.exit_time} @ $${fmt(t.exit_price)}\n`;
  text += `OUTCOME:          ${t.exit_reason} (P&L: ${fmtMoney(t.pnl_usd)} · ${t.r_multiple}R)\n`;
  text += `STOP LOSS:        $${fmt(t.stop_loss)}\n`;
  text += `TAKE PROFIT (DOL):$${fmt(t.take_profit)}\n`;
  text += `SESSION WINDOW:   ${t.session}\n\n`;
  text += `FULL STRATEGY REASONING STEP-BY-STEP:\n${t.reason}\n`;

  $("#rationale-content").textContent = text;
  $("#rationale-type-badge").textContent = `BACKTEST TRADE #${t.id} AUDIT`;
}

// 7. Load Activity Logs with Filters
async function loadActivityLogs() {
  try {
    const statusVal = $("#act-filter-status") ? $("#act-filter-status").value : "ALL";
    const intervalVal = $("#act-filter-interval") ? $("#act-filter-interval").value : "ALL";
    const searchVal = $("#act-filter-search") ? $("#act-filter-search").value.trim() : "";
    const limitVal = $("#act-filter-limit") ? $("#act-filter-limit").value : 50;

    const params = new URLSearchParams();
    if (statusVal !== "ALL") params.append("status", statusVal);
    if (intervalVal !== "ALL") params.append("interval", intervalVal);
    if (searchVal) params.append("search", searchVal);
    params.append("limit", limitVal);

    const logs = await apiGet(`/api/activity?${params.toString()}`);
    const tbody = $("#activity-tbody");
    if (!logs.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No activity logs matching the selected filters.</td></tr>`;
      return;
    }

    tbody.innerHTML = logs.map(l => `
      <tr>
        <td>#${l.id}</td>
        <td class="font-mono">${l.started_at}</td>
        <td><b>${l.symbol}</b></td>
        <td><span class="badge badge-secondary">${l.interval}</span></td>
        <td class="font-mono">${l.rows_received}</td>
        <td><span class="badge ${l.status === 'OK' ? 'badge-green' : 'badge-red'}">${l.status}</span></td>
        <td style="color: #cbd5e1;">${l.message || '—'}</td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Activity log error:", err);
  }
}

function resetActivityFilters() {
  if ($("#act-filter-status")) $("#act-filter-status").value = "ALL";
  if ($("#act-filter-interval")) $("#act-filter-interval").value = "ALL";
  if ($("#act-filter-search")) $("#act-filter-search").value = "";
  if ($("#act-filter-limit")) $("#act-filter-limit").value = "50";
  loadActivityLogs();
}

// 8. Event Listeners & Boot
document.addEventListener("DOMContentLoaded", () => {
  initTabs();

  // Timeframe buttons
  $$(".tf-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".tf-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      loadMarketChart(btn.dataset.tf);
    });
  });

  // Chart layer checkboxes & limit select
  ["layer-price", "layer-ema50", "layer-ema200", "layer-fvg"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", updateChartLayers);
  });
  if ($("#chart-limit-select")) {
    $("#chart-limit-select").addEventListener("change", () => loadMarketChart(currentTf));
  }

  // Paper Trading filters
  ["paper-filter-status", "paper-filter-side", "paper-filter-outcome", "paper-filter-date-from", "paper-filter-date-to"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", loadPaperTrading);
  });
  if ($("#paper-filter-search")) {
    $("#paper-filter-search").addEventListener("input", debounce(loadPaperTrading, 300));
  }
  if ($("#btn-reset-paper-filters")) {
    $("#btn-reset-paper-filters").addEventListener("click", resetPaperFilters);
  }

  // Backtest filters & CSV Export
  ["bt-filter-side", "bt-filter-outcome", "bt-filter-session", "bt-filter-min-r", "bt-filter-date-from", "bt-filter-date-to"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", filterBacktestTrades);
  });
  if ($("#bt-filter-search")) {
    $("#bt-filter-search").addEventListener("input", filterBacktestTrades);
  }
  if ($("#btn-reset-bt-filters")) {
    $("#btn-reset-bt-filters").addEventListener("click", resetBacktestFilters);
  }
  if ($("#btn-export-bt-csv")) {
    $("#btn-export-bt-csv").addEventListener("click", exportBacktestCsv);
  }
  // Strategy Version Switcher Buttons
  $$(".ver-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      loadBacktestData(btn.dataset.ver, false);
    });
  });

  if ($("#btn-refresh-backtest")) {
    $("#btn-refresh-backtest").addEventListener("click", () => loadBacktestData(currentBacktestVersion, true));
  }

  // Activity log filters
  ["act-filter-status", "act-filter-interval", "act-filter-limit"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", loadActivityLogs);
  });
  if ($("#act-filter-search")) {
    $("#act-filter-search").addEventListener("input", debounce(loadActivityLogs, 300));
  }
  if ($("#btn-reset-act-filters")) {
    $("#btn-reset-act-filters").addEventListener("click", resetActivityFilters);
  }

  // Evaluate Now button
  $("#btn-cycle").addEventListener("click", async () => {
    $("#btn-cycle").textContent = "Evaluating…";
    try {
      await apiPost("/api/collect-cycle");
      await refreshMarketOverview();
    } catch (e) {
      console.error(e);
    } finally {
      $("#btn-cycle").textContent = "↻ Evaluate Now";
    }
  });

  // Initial boot
  refreshMarketOverview();
  setInterval(refreshMarketOverview, 30000); // 30s auto-refresh
});

// Utility Debounce
function debounce(fn, ms) {
  let timer;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), ms);
  };
}
