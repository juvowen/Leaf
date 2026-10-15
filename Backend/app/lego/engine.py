"""Lego: takes EX's needs and the market data, and returns the stocks and pairs that meet them.

No AI here. Each need names a metric key, FUNCTIONS maps the key to its function, and the
comparison is plain arithmetic, so the same spec and the same prices always give the same answer.
"""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np

from ..ex.spec import Need, Spec
from ..metrics import METRICS
from .functions import COST_ORDER, FUNCTIONS, Pair, Stock, pair_stats, stock_stats
from .providers import Prices

MAX_RESULTS = 50  # per strategy, best fit first
CHART_DAYS = 120  # how much history the result charts show
PREFILTER = {"volatility", "avg_volume", "total_return", "corr", "hedge_effectiveness"}


def _passes(value: float, need: Need) -> bool:
    if value is None or math.isnan(value):
        return False
    v, op = need.value, need.op
    if op == "between":
        return v[0] <= value <= v[1]
    return {">": value > v, ">=": value >= v, "<": value < v, "<=": value <= v}[op]


def _margin(value: float, need: Need) -> float:
    """How far inside the need a value sits: 0 right on the line, 1 comfortably inside."""
    if math.isinf(value):
        return 1.0  # e.g. a spread that never reverts, for 'half_life > 100'
    if need.op == "between":
        lo, hi = need.value
        return float(np.clip(min(value - lo, hi - value) / ((hi - lo) / 2), 0, 1))
    m = METRICS[need.metric]
    scale = abs(need.value) or (m.hi - m.lo) / 10
    return float(np.clip(abs(value - need.value) / scale, 0, 1))


def _check(item, needs: list[Need]) -> list[float] | None:
    """The margin for each need, or None at the first need the item fails."""
    margins = []
    for n in needs:
        value = FUNCTIONS[n.metric](item)
        if not _passes(value, n):
            return None
        margins.append(_margin(value, n))
    return margins


class Lego:
    """One universe of prices. Stocks and pairs are built once and shared by every spec run on it."""

    def __init__(self, prices: Prices):
        self.prices = prices
        self.tickers = prices.tickers
        self.stocks = {
            t: Stock(prices.close[t].to_numpy(), prices.volume[t].to_numpy()) for t in self.tickers
        }
        self._pairs: dict[tuple[str, str], Pair] = {}

    def pair(self, a: str, b: str) -> Pair:
        key = (a, b)
        if key not in self._pairs:
            self._pairs[key] = Pair(self.stocks[a], self.stocks[b])
        return self._pairs[key]

    def run(self, spec: Spec) -> dict:
        """{"pairs": [...], "stocks": [...], "screened": n}, best fit first."""
        needs = sorted(spec.needs, key=lambda n: COST_ORDER.index(n.metric))
        stock_needs = [n for n in needs if METRICS[n.metric].scope == "stock"]
        pair_needs = [n for n in needs if METRICS[n.metric].scope == "pair"]

        # Stocks first: a pair can only use stocks that pass the stock needs on their own.
        stock_scores = {}
        for t, s in self.stocks.items():
            margins = _check(s, stock_needs)
            if margins is not None:
                stock_scores[t] = margins

        # Cheap needs (correlation) first. Only pairs that pass them get the slow tests.
        quick = [n for n in pair_needs if n.metric in PREFILTER]
        slow = [n for n in pair_needs if n.metric not in PREFILTER]
        pairs, screened = [], 0
        usable = [t for t in self.tickers if t in stock_scores]
        markets = self.prices.markets
        for a, b in combinations(usable, 2):
            if markets and markets[a] == markets[b]:
                continue  # a mixed scan only keeps pairs across markets
            p = self.pair(a, b)
            margins = _check(p, quick)
            if margins is None:
                continue
            screened += 1
            more = _check(p, slow)
            if more is None:
                continue
            margins += more
            # A stock need on a pair counts as well as its weaker leg meets it.
            margins += [min(x, y) for x, y in zip(stock_scores[a], stock_scores[b])]
            score = 100 * sum(margins) / len(margins) if margins else 100.0
            pairs.append((score, a, b, p))

        pairs.sort(key=lambda row: -row[0])
        why = "" if pairs else self._why_none(stock_needs, pair_needs, usable)
        return {
            "pairs": [self._pair_row(score, a, b, p) for score, a, b, p in pairs[:MAX_RESULTS]],
            "stocks": self._stock_rows(stock_scores) if stock_needs else [],
            "screened": screened,
            "matched": len(pairs),
            "why_none": why,
        }

    def _why_none(self, stock_needs: list[Need], pair_needs: list[Need], usable: list[str]) -> str:
        """Which need left nothing, and how close the market came to it. Needs are tried in the
        order the scan uses, each on what got past the ones before, so the answer names the need
        that actually emptied the list."""
        if len(usable) < 2:
            for n in stock_needs:
                values = [FUNCTIONS[n.metric](s) for s in self.stocks.values()]
                if sum(_passes(v, n) for v in values) < 2:
                    return _shortfall(n, values, "tickers", narrowed=False)
            return "Fewer than two tickers have usable prices."
        markets = self.prices.markets
        candidates = [
            self.pair(a, b) for a, b in combinations(usable, 2) if not (markets and markets[a] == markets[b])
        ]
        for i, n in enumerate(pair_needs):
            values = [FUNCTIONS[n.metric](p) for p in candidates]
            passing = [p for p, v in zip(candidates, values) if _passes(v, n)]
            if not passing:
                return _shortfall(n, values, "pairs", narrowed=i > 0)
            candidates = passing
        return ""

    def _pair_row(self, score: float, a: str, b: str, p: Pair) -> dict:
        n = min(CHART_DAYS, len(p.a.close))
        close_a, close_b = p.a.close[-n:], p.b.close[-n:]
        return {
            "a": a,
            "b": b,
            "score": round(score, 1),
            "price_a": round(float(p.a.close[-1]), 6),
            "price_b": round(float(p.b.close[-1]), 6),
            **({"market_a": self.prices.markets[a], "market_b": self.prices.markets[b]} if self.prices.markets else {}),
            **pair_stats(p),
            "series": {
                "dates": [d.strftime("%Y-%m-%d") for d in self.prices.close.index[-n:]],
                "a": np.round(100 * close_a / close_a[0], 2).tolist(),
                "b": np.round(100 * close_b / close_b[0], 2).tolist(),
                "z": np.round(p.z[-n:], 3).tolist(),
            },
        }

    def _stock_rows(self, stock_scores: dict[str, list[float]]) -> list[dict]:
        rows = [
            {
                "ticker": t,
                "score": round(100 * sum(m) / len(m), 1) if m else 100.0,
                "price": round(float(self.stocks[t].close[-1]), 6),
                **stock_stats(self.stocks[t]),
            }
            for t, m in stock_scores.items()
        ]
        return sorted(rows, key=lambda r: -r["score"])[:MAX_RESULTS]


def _need_words(n: Need) -> str:
    if n.op == "between":
        return f"between {n.value[0]:g} and {n.value[1]:g}"
    return f"{ {'>': 'above', '>=': 'at least', '<': 'below', '<=': 'at most'}[n.op] } {n.value:g}"


def _shortfall(n: Need, values: list[float], what: str, narrowed: bool) -> str:
    """'None of the 406 pairs has correlation between -0.9 and -0.5. The closest is 0.0695.'"""
    label = METRICS[n.metric].label.lower()
    left = " left after the earlier checks" if narrowed else ""
    if len(values) == 1:
        head = f"The one {what[:-1]}{left} does not have {label} {_need_words(n)}."
    else:
        head = f"None of the {len(values)} {what}{left} has {label} {_need_words(n)}."
    seen = [v for v in values if v is not None and math.isfinite(v)]
    if not seen:
        return head
    if n.op == "between":
        lo, hi = n.value
        closest = min(seen, key=lambda v: lo - v if v < lo else v - hi)
    else:
        closest = max(seen) if n.op in (">", ">=") else min(seen)
    return f"{head} The closest is {closest:.3g}."


def explain(spec: Spec, result: dict) -> str:
    """A plain reading of the result, written from the numbers (no AI)."""
    pairs = result["pairs"]
    if not pairs:
        return ""
    wanted = "; ".join(n.text() for n in spec.needs)
    one = result["matched"] == 1
    head = (
        f"{result['matched']} pair{'' if one else 's'} out of {result['screened']} screened "
        f"meet{'s' if one else ''} every need ({wanted})."
    )
    best = pairs[0]
    facts = []
    for key, label, fmt in (
        ("coint_p", "cointegration p", lambda v: "<0.001" if v < 0.001 else f"{v:.3f}"),
        ("half_life", "half-life", lambda v: f"{v:.1f} days"),
        ("corr", "correlation", lambda v: f"{v:.2f}"),
        ("zscore", "spread z now", lambda v: f"{v:+.2f}"),
    ):
        if best.get(key) is not None:
            facts.append(f"{label} {fmt(best[key])}")
    tail = f" The best fit is {best['a']}/{best['b']}: {', '.join(facts)}." if facts else ""
    return head + tail + " Statistics are in-sample, so treat them as a starting point."
