import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio import State, next_order, july_review  # noqa: E402

PRICES = {"A200": 140.0, "BGBL": 75.0, "VGE": 85.0}


def state(holdings=None, cash=1000.0, offset=30000.0, spending=6000.0, **kw):
    return State(holdings=holdings or {}, prices=PRICES, cash=cash,
                 offset_balance=offset, monthly_spending=spending, **kw)


class OffsetGate(unittest.TestCase):
    def test_skips_when_offset_below_three_months(self):
        p = next_order(state(offset=17999))
        self.assertEqual(p.action, "SKIP")
        self.assertEqual(p.orders, [])


class FirstDeployment(unittest.TestCase):
    def test_large_lump_splits_80_10_10(self):
        p = next_order(state(cash=10000))
        self.assertEqual([o.ticker for o in p.orders], ["BGBL", "A200", "VGE"])

    def test_small_lump_buys_bgbl_only(self):
        p = next_order(state(cash=4000))
        self.assertEqual([o.ticker for o in p.orders], ["BGBL"])


class OneTicketRule(unittest.TestCase):
    # roughly 10/80/10 by value
    BALANCED = {"A200": 7, "BGBL": 107, "VGE": 12}

    def test_in_band_buys_bgbl(self):
        p = next_order(state(self.BALANCED))
        self.assertEqual(len(p.orders), 1)
        self.assertEqual(p.orders[0].ticker, "BGBL")

    def test_out_of_band_buys_most_underweight(self):
        p = next_order(state({"A200": 2, "BGBL": 107, "VGE": 12}))
        self.assertEqual(p.orders[0].ticker, "A200")

    def test_overweight_sleeve_is_never_bought(self):
        # BGBL far over target: buy whichever small sleeve is lowest, not BGBL
        p = next_order(state({"A200": 2, "BGBL": 200, "VGE": 6}))
        self.assertNotEqual(p.orders[0].ticker, "BGBL")

    def test_sub_500_order_skips(self):
        p = next_order(state(self.BALANCED, cash=480))
        self.assertEqual(p.action, "SKIP")

    def test_whole_units_and_brokerage_fit_in_cash(self):
        p = next_order(state(self.BALANCED, cash=1000))
        o = p.orders[0]
        self.assertIsInstance(o.units, int)
        self.assertLessEqual(o.total, 1000)

    def test_no_sell_orders_ever(self):
        p = next_order(state({"A200": 0, "BGBL": 10, "VGE": 100}, cash=2000))
        self.assertTrue(all(o.units > 0 for o in p.orders))


class Recycling(unittest.TestCase):
    def test_three_matching_amounts(self):
        p = next_order(state(OneTicketRule.BALANCED, debt_recycling=True))
        self.assertEqual(len(set(p.recycling.values())), 1)
        self.assertEqual(p.recycling["transfer_to_pearler"], sum(o.total for o in p.orders))


class Guards(unittest.TestCase):
    def test_vge_ceiling_warns(self):
        lines = july_review(state({"A200": 7, "BGBL": 60, "VGE": 20}))
        self.assertTrue(any("15% hard stop" in l for l in lines))

    def test_unknown_ticker_rejected(self):
        import json, tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"holdings": {"NDQ": 5}, "prices": PRICES, "cash": 1000,
                       "offset_balance": 1, "monthly_spending": 1}, f)
        with self.assertRaises(ValueError):
            State.load(f.name)


if __name__ == "__main__":
    unittest.main()
