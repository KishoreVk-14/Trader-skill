"""Unit tests for Gold SMC Strategy Application."""
import unittest
import pandas as pd
from datetime import datetime, timezone
from app.smc.structure import find_swings, analyze_order_flow
from app.smc.fvg import find_fvgs, check_htf_fvg_mitigation
from app.smc.smt import detect_smt_divergence
from app.smc.strategy import check_three_candles_displacement, evaluate_strategy
from app.smc.sessions import get_session_info
from app.paper_trading.engine import process_market_candle, get_performance_summary
from app.database.db import init_db

class TestGoldSMC(unittest.TestCase):

    def setUp(self):
        init_db()

    def test_fvg_detection_and_ce50(self):
        """Tests that a 3-candle bullish gap is detected and CE is exactly at 50% midpoint."""
        candles = [
            {"datetime": "2026-11-01T10:00:00Z", "open": 2600.0, "high": 2605.0, "low": 2598.0, "close": 2604.0},
            {"datetime": "2026-11-01T10:05:00Z", "open": 2604.0, "high": 2620.0, "low": 2603.0, "close": 2618.0},
            {"datetime": "2026-11-01T10:10:00Z", "open": 2618.0, "high": 2625.0, "low": 2612.0, "close": 2622.0},
        ]
        df = pd.DataFrame(candles)
        fvgs = find_fvgs(df, min_gap_usd=0.20)
        self.assertEqual(len(fvgs), 1)
        f = fvgs[0]
        self.assertEqual(f["type"], "BULLISH")
        self.assertEqual(f["bottom"], 2605.0)  # Bar 0 High
        self.assertEqual(f["top"], 2612.0)     # Bar 2 Low
        self.assertEqual(f["ce_50"], 2608.5)   # 50% midpoint

    def test_three_candles_displacement(self):
        """Tests 3 consecutive green candles displacement on 5M."""
        green_candles = pd.DataFrame([
            {"datetime": "2026-11-01T12:00:00Z", "open": 2610.0, "high": 2612.0, "low": 2609.5, "close": 2611.5},
            {"datetime": "2026-11-01T12:05:00Z", "open": 2611.5, "high": 2615.0, "low": 2611.0, "close": 2614.5},
            {"datetime": "2026-11-01T12:10:00Z", "open": 2614.5, "high": 2618.0, "low": 2613.5, "close": 2617.5},
        ])
        disp = check_three_candles_displacement(green_candles, expected_direction="BULLISH")
        self.assertTrue(disp["passed"])
        self.assertTrue(disp["all_same_color"])

    def test_smt_divergence(self):
        """Tests Bullish SMT: Gold makes Lower Low while Silver makes Higher Low."""
        gold_df = pd.DataFrame([
            {"datetime": f"2026-11-01T10:{i:02d}:00Z", "open": 2600 - i, "high": 2602 - i, "low": 2598 - i, "close": 2599 - i}
            for i in range(25)
        ])
        # Inject swing lows: low at index 5 and lower low at index 18
        gold_df.loc[5, "low"] = 2580.0
        gold_df.loc[18, "low"] = 2570.0  # Lower Low on Gold

        silver_df = pd.DataFrame([
            {"datetime": f"2026-11-01T10:{i:02d}:00Z", "open": 30.0, "high": 30.5, "low": 29.8, "close": 30.2}
            for i in range(25)
        ])
        silver_df.loc[5, "low"] = 29.0
        silver_df.loc[18, "low"] = 29.5  # Higher Low on Silver

        smt = detect_smt_divergence(gold_df, silver_df)
        self.assertTrue(smt["has_smt"])
        self.assertEqual(smt["type"], "BULLISH_SMT")

    def test_session_killzones(self):
        """Tests London and NY Killzone detection."""
        london_time = datetime(2026, 11, 2, 8, 30, tzinfo=timezone.utc)  # Monday 08:30 UTC
        info = get_session_info(london_time)
        self.assertTrue(info["is_killzone"])
        self.assertEqual(info["session"], "LONDON_OPEN_KILLZONE")

        weekend_time = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)  # Saturday
        info_we = get_session_info(weekend_time)
        self.assertTrue(info_we["is_weekend"])
        self.assertFalse(info_we["allowed_to_trade"])

    def test_fvg_persists_during_retracement(self):
        """Tests that a 5M Bullish FVG remains active and passed when a subsequent pullback candle forms."""
        candles = pd.DataFrame([
            {"datetime": "2026-11-01T12:00:00Z", "open": 2610.0, "high": 2612.0, "low": 2609.5, "close": 2611.5},
            {"datetime": "2026-11-01T12:05:00Z", "open": 2611.5, "high": 2615.0, "low": 2611.0, "close": 2614.5},
            {"datetime": "2026-11-01T12:10:00Z", "open": 2614.5, "high": 2620.0, "low": 2613.5, "close": 2619.5},
            # Pullback / entry candle (red candle testing into the FVG)
            {"datetime": "2026-11-01T12:15:00Z", "open": 2619.5, "high": 2619.8, "low": 2613.0, "close": 2614.0},
        ])
        disp = check_three_candles_displacement(candles, expected_direction="BULLISH")
        self.assertTrue(disp["passed"])
        self.assertTrue(disp["fvg_formed"])
        self.assertEqual(disp["bottom"], 2612.0)
        self.assertEqual(disp["top"], 2613.5)

    def test_smt_no_false_positive(self):
        """Tests that when Gold and Silver move in sync (no divergence), SMT is reported as False."""
        gold_df = pd.DataFrame([
            {"datetime": f"2026-11-01T10:{i*5:02d}:00Z", "open": 2600.0, "high": 2605.0, "low": 2595.0, "close": 2602.0}
            for i in range(12)
        ])
        silver_df = pd.DataFrame([
            {"datetime": f"2026-11-01T10:{i*5:02d}:00Z", "open": 30.0, "high": 30.5, "low": 29.5, "close": 30.2}
            for i in range(12)
        ])
        smt = detect_smt_divergence(gold_df, silver_df)
        self.assertFalse(smt["has_smt"])
        self.assertEqual(smt["type"], "NONE")

if __name__ == "__main__":
    unittest.main()
