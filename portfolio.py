"""Deterministic order engine for the three-ETF Pearler account.

The agent never does arithmetic in its head: it calls this module and reports
what comes back. Buy orders only. There is no code path that produces a sell.

Usage:
    python3 portfolio.py next   --state private/state.json
    python3 portfolio.py review --state private/state.json
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field

TARGETS = {"A200": 0.10, "BGBL": 0.80, "VGE": 0.10}
DEFAULT_TICKER = "BGBL"
BAND = 0.05              # act only when a sleeve is more than 5 points off target
VGE_CEILING = 0.15       # hard stop
MIN_ORDER = 500.00       # AUD, approximate ASX minimum parcel
BROKERAGE = 6.50         # AUD per executed order (5.50 with Prepay credit)
OFFSET_MONTHS = 3        # emergency buffer held in the home-loan offset


@dataclass
class State:
    holdings: dict[str, int]          # ticker -> whole units held
    prices: dict[str, float]          # ticker -> last price, AUD
    cash: float                       # AUD available to invest this month
    offset_balance: float             # AUD in the home-loan offset
    monthly_spending: float           # AUD
    brokerage: float = BROKERAGE
    debt_recycling: bool = False

    @classmethod
    def load(cls, path: str) -> "State":
        with open(path) as f:
            raw = json.load(f)
        unknown = set(raw.get("holdings", {})) - set(TARGETS)
        if unknown:
            raise ValueError(f"Holdings outside the brief: {sorted(unknown)}")
        return cls(**raw)


@dataclass
class Order:
    ticker: str
    units: int
    price: float
    brokerage: float

    @property
    def gross(self) -> float:
        return round(self.units * self.price, 2)

    @property
    def total(self) -> float:
        return round(self.gross + self.brokerage, 2)


@dataclass
class Plan:
    action: str                       # "BUY" or "SKIP"
    reason: str
    orders: list[Order] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    leftover_cash: float = 0.0
    recycling: dict[str, float] | None = None
    warnings: list[str] = field(default_factory=list)


def weights(holdings: dict[str, int], prices: dict[str, float]) -> dict[str, float]:
    values = {t: holdings.get(t, 0) * prices[t] for t in TARGETS}
    total = sum(values.values())
    if total == 0:
        return {t: 0.0 for t in TARGETS}
    return {t: v / total for t, v in values.items()}


def choose_ticker(w: dict[str, float]) -> tuple[str, str]:
    """One-ticket rule. Returns (ticker, reason).

    The brief says "if any sleeve is more than 5 points off, put the whole
    contribution into that ticker". Read literally that would buy more of an
    overweight sleeve, so: when anything is out of band, buy the sleeve furthest
    *below* target. That is the only way new money closes the gap.
    """
    out_of_band = [t for t in TARGETS if abs(w[t] - TARGETS[t]) > BAND]
    if not out_of_band:
        return DEFAULT_TICKER, "All sleeves inside the 5-point band, so BGBL only."
    most_under = min(TARGETS, key=lambda t: w[t] - TARGETS[t])
    gap = (TARGETS[most_under] - w[most_under]) * 100
    return most_under, (
        f"Out of band: {', '.join(out_of_band)}. "
        f"{most_under} is furthest under target ({gap:.1f} points)."
    )


def _order(ticker: str, budget: float, s: State) -> Order | None:
    units = math.floor((budget - s.brokerage) / s.prices[ticker])
    if units <= 0 or units * s.prices[ticker] < MIN_ORDER:
        return None
    return Order(ticker, units, s.prices[ticker], s.brokerage)


def _check_ticker(s: State, w: dict[str, float]) -> list[str]:
    warns = []
    if w["VGE"] > VGE_CEILING:
        warns.append(f"VGE is {w['VGE']:.1%}, above the 15% hard stop. Do not add to it.")
    return warns


def next_order(s: State) -> Plan:
    buffer = OFFSET_MONTHS * s.monthly_spending
    if s.offset_balance < buffer:
        return Plan("SKIP", f"Offset ${s.offset_balance:,.2f} is below the "
                    f"{OFFSET_MONTHS}-month buffer of ${buffer:,.2f}. No transfer this month.")

    w = weights(s.holdings, s.prices)
    first_deployment = sum(s.holdings.get(t, 0) for t in TARGETS) == 0
    orders: list[Order] = []

    if first_deployment:
        split = [_order(t, s.cash * TARGETS[t], s) for t in ("BGBL", "A200", "VGE")]
        if all(split):
            orders, reason = split, "First deployment: lump clears three $500 tickets, so 80/10/10."
        else:
            o = _order("BGBL", s.cash, s)
            orders = [o] if o else []
            reason = ("First deployment: lump too small for three $500 tickets. "
                      "BGBL now; A200 and VGE on the next two months.")
    else:
        ticker, reason = choose_ticker(w)
        o = _order(ticker, s.cash, s)
        orders = [o] if o else []

    if not orders:
        return Plan("SKIP", f"${s.cash:,.2f} cannot buy a $500 parcel after brokerage. "
                    "Accumulate in Pearler cash or the offset.", weights=w)

    spent = sum(o.total for o in orders)
    plan = Plan("BUY", reason, orders, w, round(s.cash - spent, 2), warnings=_check_ticker(s, w))
    if s.debt_recycling:
        # The amount redrawn must equal the amount invested, to the cent.
        plan.recycling = {"pay_onto_home_split": spent,
                          "redraw_from_investment_split": spent,
                          "transfer_to_pearler": spent}
    return plan


def july_review(s: State) -> list[str]:
    w = weights(s.holdings, s.prices)
    lines = [f"{t}: {w[t]:.1%} (target {TARGETS[t]:.0%})" for t in TARGETS]
    under = min(TARGETS, key=lambda t: w[t] - TARGETS[t])
    lines.append(f"Most underweight: {under}. Fix with new money only, never by sale.")
    lines += _check_ticker(s, w)
    return lines


def _print_plan(p: Plan) -> None:
    print(f"{p.action}: {p.reason}")
    for o in p.orders:
        print(f"  {o.ticker}  {o.units} units @ ${o.price:.2f} = ${o.gross:,.2f}"
              f" + ${o.brokerage:.2f} brokerage = ${o.total:,.2f}")
    if p.orders:
        print(f"  Cash left over: ${p.leftover_cash:,.2f}")
    if p.recycling:
        for k, v in p.recycling.items():
            print(f"  {k.replace('_', ' ')}: ${v:,.2f}")
    for wmsg in p.warnings:
        print(f"  WARNING: {wmsg}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["next", "review"])
    ap.add_argument("--state", default="private/state.json")
    args = ap.parse_args()
    state = State.load(args.state)
    if args.command == "next":
        _print_plan(next_order(state))
    else:
        print("\n".join(july_review(state)))
