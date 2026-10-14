"""Tests for Lego. Synthetic data only: Yahoo is always a stand-in here, never the network."""
import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.ex.spec import Need, parse_spec
from app.lego import providers
from app.lego.engine import Lego, _margin, _passes, explain
from app.lego.functions import COST_ORDER, FUNCTIONS, Pair, Stock
from app.lego.presets import PRESETS
from app.lego.providers import ProviderError, get_prices
from app.main import app
from app.metrics import METRICS

client = TestClient(app)


def found(spec, days=750):
    lego = Lego(get_prices("synthetic", None, days))
    return {(r["a"], r["b"]) for r in lego.run(spec)["pairs"]}


# ---------- the metric list and the functions agree ----------

def test_every_metric_has_exactly_one_function():
    assert set(FUNCTIONS) == set(METRICS)
    assert sorted(COST_ORDER) == sorted(METRICS)


# ---------- the functions ----------

def series(rng, n=1000):
    return np.cumsum(rng.normal(0, 0.01, n))


def test_half_life_recovers_a_known_reversion_speed():
    rng = np.random.default_rng(1)
    theta, n = 0.1, 5000
    s = np.zeros(n)
    for i in range(1, n):
        s[i] = s[i - 1] * (1 - theta) + rng.normal(0, 0.01)
    a = series(rng, n)
    pair = Pair(Stock(100 * np.exp(a + s), np.ones(n)), Stock(100 * np.exp(a), np.ones(n)))
    assert pair.half_life == pytest.approx(math.log(2) / theta, rel=0.15)
    assert pair.coint_p < 0.01


def test_a_spread_that_never_reverts_has_a_high_p_value():
    rng = np.random.default_rng(2)
    a, b = series(rng), series(rng)
    pair = Pair(Stock(100 * np.exp(a), np.ones(1000)), Stock(100 * np.exp(b), np.ones(1000)))
    assert pair.coint_p > 0.05


def test_hedge_effectiveness_is_correlation_squared_and_beta_is_cov_over_var():
    rng = np.random.default_rng(3)
    a = series(rng)
    b = 0.5 * a + series(rng) * 0.3
    pair = Pair(Stock(100 * np.exp(a), np.ones(1000)), Stock(100 * np.exp(b), np.ones(1000)))
    ra, rb = pair.a.returns, pair.b.returns
    assert pair.hedge_effectiveness == pytest.approx(np.corrcoef(ra, rb)[0, 1] ** 2)
    assert pair.return_beta == pytest.approx(np.cov(ra, rb)[0, 1] / np.var(rb, ddof=1))
    assert pair.spread_z_abs == abs(pair.spread_z)


def test_stock_metrics():
    close = np.array([100.0, 110.0, 99.0, 120.0])
    s = Stock(close, np.array([10.0, 20.0, 30.0, 40.0]))
    assert s.total_return == pytest.approx(0.2)
    assert s.avg_volume == 25
    assert s.volatility == pytest.approx(np.std(np.diff(close) / close[:-1], ddof=1) * math.sqrt(252))


# ---------- comparing and scoring ----------

@pytest.mark.parametrize("value,op,limit,ok", [
    (0.04, "<=", 0.05, True), (0.05, "<=", 0.05, True), (0.05, "<", 0.05, False),
    (3, ">", 2, True), (2, ">=", 2, True), (5, "between", (3, 40), True), (41, "between", (3, 40), False),
    (math.inf, "<=", 40, False), (math.inf, ">", 100, True), (math.nan, ">", 0, False),
])
def test_passes(value, op, limit, ok):
    assert _passes(value, Need("half_life", op, limit)) is ok


def test_margin_is_zero_on_the_line_and_one_well_inside():
    need = Need("coint_p", "<=", 0.05)
    assert _margin(0.05, need) == 0
    assert _margin(0.0, need) == 1
    assert _margin(21.5, Need("half_life", "between", (3, 40))) == 1


# ---------- the planted synthetic pairs land where they should ----------

def test_presets_find_the_planted_pairs():
    assert found(PRESETS["mean_reversion"]) == {("CO1A", "CO1B"), ("CO2A", "CO2B")}
    assert ("CO1A", "CO1B") in found(PRESETS["arbitrage"])
    assert found(PRESETS["hedging"]) == {("HC1A", "HC1B"), ("HC2A", "HC2B")}


def test_hedging_pairs_move_opposite():
    lego = Lego(get_prices("synthetic", None, 750))
    rows = lego.run(PRESETS["hedging"])["pairs"]
    assert rows and all(-0.9 <= r["corr"] <= -0.5 and r["return_beta"] < 0 for r in rows)


@pytest.mark.parametrize("days", [21, 63, 126, 252, 756])  # the screener's 1M to 3Y choices
def test_every_screener_period_scans(days):
    r = client.post("/api/scan/multi", json={"strategies": list(PRESETS), "provider": "synthetic", "days": days})
    assert r.status_code == 200
    rows = [row for block in r.json()["strategies"].values() for row in block["results"]]
    assert all(len(row["series"]["dates"]) == min(days, 120) for row in rows)


def test_unrelated_random_walks_never_match():
    for spec in PRESETS.values():
        assert not any(t.startswith("RW") for pair in found(spec) for t in pair)


def test_results_are_best_fit_first_with_chart_series():
    lego = Lego(get_prices("synthetic", None, 750))
    rows = lego.run(PRESETS["mean_reversion"])["pairs"]
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)
    s = rows[0]["series"]
    assert len(s["dates"]) == len(s["a"]) == len(s["b"]) == len(s["z"]) == 120
    assert s["a"][0] == s["b"][0] == 100


def test_stock_needs_filter_both_legs_and_are_listed():
    spec = parse_spec({"name": "calm", "needs": [{"metric": "volatility", "op": "<", "value": 0.2}]})
    lego = Lego(get_prices("synthetic", None, 750))
    result = lego.run(spec)
    calm = {s["ticker"] for s in result["stocks"]}
    assert calm and all(s["volatility"] < 0.2 for s in result["stocks"])
    assert all(r["a"] in calm and r["b"] in calm for r in result["pairs"])


def test_the_same_inputs_always_give_the_same_answer():
    assert found(PRESETS["hedging"]) == found(PRESETS["hedging"])
    a = get_prices("synthetic", ["CO1A", "RW1"], 300).close
    b = get_prices("synthetic", ["CO1A", "RW1"], 300).close
    pd.testing.assert_frame_equal(a, b)


def test_explanation_names_the_best_pair():
    lego = Lego(get_prices("synthetic", None, 750))
    result = lego.run(PRESETS["arbitrage"])
    text = explain(PRESETS["arbitrage"], result)
    best = result["pairs"][0]
    assert f"{best['a']}/{best['b']}" in text
    assert explain(PRESETS["arbitrage"], {"pairs": [], "matched": 0, "screened": 0}) == ""


# ---------- providers ----------

@pytest.mark.parametrize("kwargs,words", [
    ({"provider": "bloomberg", "tickers": None, "days": 750}, "not a data source"),
    ({"provider": "synthetic", "tickers": ["CO1A"], "days": 750}, "at least two"),
    ({"provider": "synthetic", "tickers": None, "days": 10}, "Lookback"),
    ({"provider": "synthetic", "tickers": [f"T{i}" for i in range(151)], "days": 750}, "150 or fewer"),
    ({"provider": "yahoo", "tickers": None, "days": 750, "asset_class": "bonds"}, "not an asset class"),
])
def test_bad_requests_say_what_is_wrong(kwargs, words):
    with pytest.raises(ProviderError) as info:
        get_prices(**kwargs)
    assert words in info.value.message


def fake_yahoo(calls, data):
    """Stands in for the yfinance download. Records which tickers were asked for."""
    def download(tickers, start):
        calls.append(list(tickers))
        return {t: data[t] for t in tickers if t in data}
    return download


def frame(n=400, seed=0):
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = 100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 0.01, n)))
    return pd.DataFrame({"Close": close, "Volume": 1e6}, index=idx)


def test_yahoo_uses_the_cache_the_second_time(monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "_download", fake_yahoo(calls, {"AAA": frame(seed=1), "BBB": frame(seed=2)}))
    first = get_prices("yahoo", ["AAA", "BBB"], 250)
    second = get_prices("yahoo", ["aaa", "BBB"], 250)
    assert calls == [["AAA", "BBB"]]  # downloaded once, then read from disk
    pd.testing.assert_frame_equal(first.close, second.close)
    assert first.close.shape == (250, 2)
    assert first.fetched_at is not None and second.fetched_at <= dt.datetime.now().astimezone()


def test_yahoo_downloads_again_once_the_cache_is_stale(monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "_download", fake_yahoo(calls, {"AAA": frame(seed=1), "BBB": frame(seed=2)}))
    get_prices("yahoo", ["AAA", "BBB"], 250)
    monkeypatch.setattr(providers, "CACHE_MAX_AGE", dt.timedelta(0))
    get_prices("yahoo", ["AAA", "BBB"], 250)
    assert len(calls) == 2


def test_yahoo_drops_unknown_and_short_tickers(monkeypatch):
    data = {"AAA": frame(seed=1), "BBB": frame(seed=2), "NEW": frame(n=50, seed=3)}
    monkeypatch.setattr(providers, "_download", fake_yahoo([], data))
    prices = get_prices("yahoo", ["AAA", "BBB", "NEW", "NOPE"], 250)
    assert prices.tickers == ["AAA", "BBB"] and prices.dropped == ["NEW", "NOPE"]


def test_yahoo_with_nothing_usable_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(providers, "_download", fake_yahoo([], {}))
    with pytest.raises(ProviderError) as info:
        get_prices("yahoo", ["NOPE", "NADA"], 250)
    assert "NOPE" in info.value.message


# ---------- the endpoints ----------

def test_universe_endpoint():
    r = client.get("/api/universe/synthetic")
    assert r.status_code == 200 and "CO1A" in r.json()["tickers"]
    assert client.get("/api/universe/nope").status_code == 404
    assert client.get("/api/universe/yahoo?asset_class=bonds").status_code == 422


@pytest.mark.parametrize("asset_class,member", [
    ("stock", "AAPL"), ("crypto", "BTC-USD"), ("forex", "EURUSD=X"), ("commodity", "GC=F"),
])
def test_each_asset_class_has_its_own_universe(asset_class, member):
    tickers = client.get(f"/api/universe/yahoo?asset_class={asset_class}").json()["tickers"]
    assert member in tickers and len(set(tickers)) == len(tickers)
    assert 2 <= len(tickers) <= providers.MAX_TICKERS
    others = set().union(*(v for k, v in providers.YAHOO_UNIVERSES.items() if k != asset_class))
    assert not others & set(tickers)


def test_crypto_asks_for_calendar_days(monkeypatch):
    seen = {}
    def fake(tickers, days, calendar_days=None):
        seen.update(days=days, calendar_days=calendar_days)
        raise ProviderError("stop")
    monkeypatch.setattr(providers, "_yahoo", fake)
    with pytest.raises(ProviderError):
        get_prices("yahoo", None, 252, "crypto")
    assert seen == {"days": 365, "calendar_days": 365}


def test_scan_multi_matches_what_the_screener_reads():
    r = client.post("/api/scan/multi", json={"strategies": ["mean_reversion", "hedging"], "provider": "synthetic", "days": 750})
    assert r.status_code == 200
    body = r.json()
    assert body["universe_size"] == 12 and body["pairs_screened"] > 0
    assert body["as_of"]["date"] and body["as_of"]["fetched_at"] is None  # synthetic has no fetch time
    assert set(body["strategies"]) == {"mean_reversion", "hedging"}
    row = body["strategies"]["mean_reversion"]["results"][0]
    for key in ("a", "b", "score", "corr", "coint_p", "half_life", "zscore", "hedge_ratio",
                "return_beta", "hedge_effectiveness", "spread_std", "vol_a", "vol_b", "series",
                "price_a", "price_b"):
        assert key in row
    assert body["strategies"]["mean_reversion"]["explanation"]


def test_scan_multi_uses_a_spec_from_ex_instead_of_the_preset():
    spec = {"name": "strong inverse", "needs": [{"metric": "corr", "op": "<=", "value": -0.85}]}
    r = client.post("/api/scan/multi", json={"strategies": ["mean_reversion"], "specs": {"mean_reversion": spec}})
    pairs = {(x["a"], x["b"]) for x in r.json()["strategies"]["mean_reversion"]["results"]}
    assert pairs == {("HC1A", "HC1B")}


def test_scan_multi_unknown_strategy_without_a_spec_is_a_422():
    r = client.post("/api/scan/multi", json={"strategies": ["momentum"]})
    assert r.status_code == 422 and "momentum" in r.json()["detail"]


def test_lego_scan_takes_an_ex_spec_directly():
    spec = {"name": "x", "needs": [{"metric": "coint_p", "op": "<=", "value": [0.01]}], "unmapped": []}
    r = client.post("/api/lego/scan", json={"spec": spec, "provider": "synthetic"})
    assert r.status_code == 200
    assert ("CO1A", "CO1B") in {(p["a"], p["b"]) for p in r.json()["pairs"]}


def test_lego_scan_bad_spec_and_bad_provider_are_plain_errors():
    r = client.post("/api/lego/scan", json={"spec": {"needs": [{"metric": "rsi", "op": ">", "value": 70}]}})
    assert r.status_code == 422 and "rsi" in r.json()["detail"]
    good = {"needs": [{"metric": "corr", "op": ">=", "value": 0.5}]}
    r = client.post("/api/lego/scan", json={"spec": good, "provider": "bloomberg"})
    assert r.status_code == 404 and isinstance(r.json()["detail"], str)
