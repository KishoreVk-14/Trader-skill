import unittest
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

from _load import ROOT

# Add trader-timemachine to sys.path to access market and backtest
TM_DIR = os.path.join(ROOT, "trader-timemachine")
if TM_DIR not in sys.path:
    sys.path.insert(0, TM_DIR)

import market
import backtest


class MultiMarketDetection(unittest.TestCase):
    def test_us_stocks(self):
        self.assertEqual(market.detect_market("TSLA"), market.MARKET_US)
        self.assertEqual(market.detect_market("AAPL"), market.MARKET_US)
        self.assertEqual(market.detect_market("BRK.B"), market.MARKET_US)

    def test_indian_stocks(self):
        self.assertEqual(market.detect_market("RELIANCE.NS"), market.MARKET_INDIA)
        self.assertEqual(market.detect_market("TCS.NS"), market.MARKET_INDIA)
        self.assertEqual(market.detect_market("INFY.BO"), market.MARKET_INDIA)

    def test_crypto(self):
        self.assertEqual(market.detect_market("BTC-USD"), market.MARKET_CRYPTO)
        self.assertEqual(market.detect_market("ETH-USDT"), market.MARKET_CRYPTO)
        self.assertEqual(market.detect_market("SOL"), market.MARKET_CRYPTO)

    def test_forex(self):
        self.assertEqual(market.detect_market("EURUSD=X"), market.MARKET_FOREX)
        self.assertEqual(market.detect_market("GBPUSD=X"), market.MARKET_FOREX)
        self.assertEqual(market.detect_market("EUR/USD"), market.MARKET_FOREX)

    def test_yahoo_symbol_normalization(self):
        self.assertEqual(market.normalize_yahoo_symbol("BRK.B"), "BRK-B")
        self.assertEqual(market.normalize_yahoo_symbol("RELIANCE.NS"), "RELIANCE.NS")
        self.assertEqual(market.normalize_yahoo_symbol("EURUSD=X"), "EURUSD=X")
        self.assertEqual(market.normalize_yahoo_symbol("EUR/USD"), "EURUSD=X")
        self.assertEqual(market.normalize_yahoo_symbol("BTC"), "BTC-USD")


class BacktestStats(unittest.TestCase):
    def test_calculate_stats_empty(self):
        stats = backtest.calculate_stats("TEST", "us", [])
        self.assertEqual(stats["total_trades"], 0)
        self.assertEqual(stats["win_rate"], 0.0)

    def test_calculate_stats_metrics(self):
        fake_trades = [
            {"r_earned": 1.5},
            {"r_earned": -1.0},
            {"r_earned": 1.5},
            {"r_earned": -1.0},
            {"r_earned": 1.5},
        ]
        stats = backtest.calculate_stats("TEST", "us", fake_trades)
        self.assertEqual(stats["total_trades"], 5)
        self.assertEqual(stats["wins"], 3)
        self.assertEqual(stats["losses"], 2)
        self.assertEqual(stats["win_rate"], 60.0)
        self.assertAlmostEqual(stats["total_r"], 2.5)
        self.assertAlmostEqual(stats["avg_r"], 0.5)
        self.assertAlmostEqual(stats["profit_factor"], 2.25)
