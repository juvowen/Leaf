"""Where Lego's market data comes from: daily close and volume, one column per ticker.

Two providers, picked by name:
  - "synthetic": made-up prices with known structure, so the math can be checked offline.
  - "yahoo": real daily prices through yfinance, cached on disk for the day.
"""
from __future__ import annotations

import datetime as dt
import logging
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import BACKEND_DIR

PROVIDERS = ("synthetic", "yahoo")
MIN_DAYS, MAX_DAYS = 21, 2520  # one month to ten years of trading days. Under ~6 months the tests get shaky.
MAX_TICKERS = 150  # 150 tickers is 11,175 pairs. Only pairs past the correlation prefilter get the slow tests
CACHE_DIR = BACKEND_DIR / ".cache" / "yahoo"
CACHE_MAX_AGE = dt.timedelta(minutes=15)  # during market hours the latest close is the live price

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """A data problem the caller can act on. `status` is the HTTP status the API should return."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class Prices:
    """Aligned daily data. Rows are dates, columns are tickers, with no gaps."""

    close: pd.DataFrame
    volume: pd.DataFrame
    dropped: list[str] = field(default_factory=list)  # asked for, but not enough data
    fetched_at: dt.datetime | None = None  # when the oldest of these prices came from the source

    @property
    def tickers(self) -> list[str]:
        return list(self.close.columns)


# ---------- the default universes ----------

# Real Yahoo Finance symbols, one list per asset class, grouped so there are pairs worth
# finding: same-sector names, and funds or contracts that track the same thing, which should
# come out cointegrated. A scan stays inside one asset class.
ASSET_CLASSES = ("stock", "crypto", "forex", "commodity")

YAHOO_UNIVERSES = {
    # Stocks and equity funds. Stocks almost never move opposite each other, so volatility
    # (VIXY) and an inverse S&P fund (SH) are there for hedging.
    "stock": [
        "KO", "PEP", "XOM", "CVX", "COP", "JPM", "BAC", "C", "WFC", "V", "MA", "HD", "LOW",
        "MCD", "YUM", "UPS", "FDX", "SPY", "IVV", "QQQ", "EWA", "EWC", "VIXY", "SH",
        # tech and chips (GOOGL/GOOG are two share classes of one company)
        "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "NVDA", "AMD", "INTC", "AVGO",
        "QCOM", "TXN", "MU", "ORCL", "CRM", "ADBE", "IBM", "CSCO", "SMH", "SOXX",
        # banks, brokers, cards, insurers
        "GS", "MS", "SCHW", "USB", "PNC", "TFC", "AXP", "PYPL", "CB", "TRV", "ALL", "PGR",
        # oil services, producers, refiners
        "SLB", "HAL", "EOG", "OXY", "MPC", "PSX", "VLO", "XLE",
        # pharma and health insurers
        "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY", "AMGN", "GILD", "UNH", "CVS", "CI",
        # consumer staples and retail
        "PG", "CL", "KMB", "WMT", "COST", "TGT", "MDLZ", "GIS", "HSY", "MO", "PM",
        "SBUX", "CMG", "NKE", "TJX", "ROST",
        # industrials, defense, railroads, airlines
        "CAT", "DE", "HON", "GE", "MMM", "LMT", "NOC", "RTX", "GD", "BA",
        "UNP", "CSX", "NSC", "DAL", "UAL", "AAL", "LUV",
        # telecom, utilities, autos, media
        "T", "VZ", "TMUS", "DUK", "SO", "NEE", "AEP", "D", "GM", "F", "DIS", "NFLX", "CMCSA",
        # more index funds (VOO tracks the S&P 500 like SPY/IVV)
        "VOO", "DIA", "IWM",
    ],
    # Coins priced in dollars. Some Yahoo symbols carry an id (UNI7083-USD) because the
    # short name is taken.
    "crypto": [
        "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD", "ADA-USD", "DOGE-USD", "TRX-USD",
        "AVAX-USD", "DOT-USD", "LINK-USD", "LTC-USD", "BCH-USD", "XLM-USD", "ETC-USD", "XMR-USD",
        "ATOM-USD", "NEAR-USD", "AAVE-USD", "HBAR-USD", "ALGO-USD", "FIL-USD", "ICP-USD",
        "SHIB-USD", "UNI7083-USD", "SUI20947-USD", "APT21794-USD", "VET-USD", "EOS-USD",
    ],
    # Currency pairs, with the crosses that should tie back to them (EURJPY to EURUSD and
    # USDJPY), and the currency funds that track them (FXE/EURUSD, UUP against the basket).
    "forex": [
        "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "NZDUSD=X", "USDCAD=X", "USDCHF=X",
        "EURGBP=X", "EURJPY=X", "GBPJPY=X", "EURCHF=X", "AUDJPY=X", "AUDNZD=X", "EURAUD=X",
        "EURCAD=X", "CADJPY=X", "CHFJPY=X", "GBPCHF=X", "EURNOK=X", "EURSEK=X",
        "USDSEK=X", "USDNOK=X", "USDMXN=X", "USDZAR=X", "USDSGD=X", "USDCNY=X", "USDINR=X",
        "USDPLN=X", "USDKRW=X",
        "UUP", "FXE", "FXY", "FXB", "FXA", "FXC", "FXF",
    ],
    # Front-month futures and the funds that hold them (GC=F/GLD/IAU, CL=F/USO, NG=F/UNG).
    "commodity": [
        # metals
        "GC=F", "SI=F", "PL=F", "PA=F", "HG=F", "GLD", "IAU", "SLV", "PPLT", "PALL", "CPER", "GDX",
        # energy
        "CL=F", "BZ=F", "NG=F", "HO=F", "RB=F", "USO", "BNO", "UNG",
        # grains and softs
        "ZC=F", "ZW=F", "KE=F", "ZS=F", "ZM=F", "ZL=F", "ZO=F", "KC=F", "SB=F", "CC=F", "CT=F",
        "OJ=F", "CORN", "WEAT", "SOYB",
        # livestock and broad baskets
        "LE=F", "GF=F", "HE=F", "DBA", "DBC",
    ],
}

# Made-up names. COxA/COxB are cointegrated (CO1 reverts fast, CO2 slower), HCxA/HCxB move
# opposite each other day to day with no long-run link (hedges), RWx are unrelated.
SYNTHETIC_UNIVERSE = ["CO1A", "CO1B", "CO2A", "CO2B", "HC1A", "HC1B", "HC2A", "HC2B", "RW1", "RW2", "RW3", "RW4"]


def default_universe(provider: str, asset_class: str = "stock") -> list[str]:
    """The synthetic names are one made-up market, so they ignore the asset class."""
    _check_provider(provider)
    _check_asset_class(asset_class)
    return list(YAHOO_UNIVERSES[asset_class] if provider == "yahoo" else SYNTHETIC_UNIVERSE)


def get_prices(provider: str, tickers: list[str] | None, days: int, asset_class: str = "stock") -> Prices:
    """Close and volume for `days` trading days, ending at the latest close."""
    _check_provider(provider)
    _check_asset_class(asset_class)
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise ProviderError(f"Lookback must be between {MIN_DAYS} and {MAX_DAYS} trading days, not {days}.")

    tickers = _clean_tickers(tickers) or default_universe(provider, asset_class)
    if len(tickers) < 2:
        raise ProviderError("Add at least two tickers. A pair needs two.")
    if len(tickers) > MAX_TICKERS:
        raise ProviderError(f"That is {len(tickers)} tickers. Keep it to {MAX_TICKERS} or fewer.")

    if provider == "yahoo" and asset_class == "crypto":
        # Crypto trades every day, so the same stretch of calendar time has more rows.
        prices = _yahoo(tickers, days * 365 // 252, calendar_days=days * 365 // 252)
    else:
        prices = _synthetic(tickers, days) if provider == "synthetic" else _yahoo(tickers, days)
    if len(prices.tickers) < 2:
        missing = ", ".join(prices.dropped) or "the tickers"
        raise ProviderError(f"Not enough data to form a pair. No usable prices for: {missing}.")
    return prices


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ProviderError(f'"{provider}" is not a data source. Use one of: {", ".join(PROVIDERS)}.', 404)


def _check_asset_class(asset_class: str) -> None:
    if asset_class not in ASSET_CLASSES:
        raise ProviderError(f'"{asset_class}" is not an asset class. Use one of: {", ".join(ASSET_CLASSES)}.')


def _clean_tickers(tickers: list[str] | None) -> list[str]:
    seen: dict[str, None] = {}
    for t in tickers or []:
        t = str(t).strip().upper()
        if t:
            seen.setdefault(t, None)
    return list(seen)


def _align(close: pd.DataFrame, volume: pd.DataFrame, days: int, asked: list[str]) -> Prices:
    """Keep the last `days` rows, fill one-off gaps, and drop tickers that still have holes."""
    close = close.sort_index().ffill(limit=3).tail(days)
    volume = volume.reindex(close.index).fillna(0)
    usable = [t for t in asked if t in close and close[t].notna().all() and (close[t] > 0).all()]
    dropped = [t for t in asked if t not in usable]
    return Prices(close[usable].astype(float), volume[usable].astype(float), dropped)


# ---------- synthetic ----------

def _synthetic(tickers: list[str], days: int) -> Prices:
    """Deterministic. One long history is built and cut to `days`, like real data would be."""
    rng = np.random.default_rng(20_240_601)
    n = MAX_DAYS
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    logs: dict[str, np.ndarray] = {}

    def walk(step: float) -> np.ndarray:
        return np.cumsum(rng.normal(0, step, n))

    def reverting(theta: float, step: float) -> np.ndarray:
        s = np.zeros(n)
        for i in range(1, n):
            s[i] = s[i - 1] * (1 - theta) + rng.normal(0, step)
        return s

    # (A leg, B leg, how B is built from A)
    planted = {
        "CO1": lambda a: 0.8 * a + reverting(0.15, 0.01),
        "CO2": lambda a: 0.8 * a + reverting(0.08, 0.01),
        "HC1": lambda a: -0.9 * a + walk(0.006),
        "HC2": lambda a: -1.0 * a + walk(0.009),
    }
    for name, make_b in planted.items():
        a = walk(0.012)
        logs[f"{name}A"], logs[f"{name}B"] = a, make_b(a)

    out = {}
    for t in tickers:
        series = logs.get(t)
        if series is None:  # any other name is an unrelated random walk, seeded by its name
            series = np.cumsum(np.random.default_rng(zlib.crc32(t.encode())).normal(0.0002, 0.014, n))
        out[t] = 100 * np.exp(series - series[-days])  # starts near 100 at the window start
    close = pd.DataFrame(out, index=dates)
    volume = pd.DataFrame(
        {t: np.random.default_rng(zlib.crc32(t.encode()) + 1).lognormal(14, 0.4, n) for t in tickers},
        index=dates,
    ).round()
    return _align(close, volume, days, tickers)


# ---------- yahoo ----------

def _yahoo(tickers: list[str], days: int, calendar_days: int | None = None) -> Prices:
    """Real daily data. Each ticker is downloaded at most every CACHE_MAX_AGE, then read from disk."""
    # Trading days are about 252 of 365, so ask for a bit more calendar time than needed.
    span = calendar_days if calendar_days is not None else int(days * 365 / 252)
    start = dt.date.today() - dt.timedelta(days=span + 14)
    cached, fetched = {}, {}
    for t in tickers:
        cached[t], fetched[t] = _read_cache(t, start) or (None, None)
    need = [t for t, frame in cached.items() if frame is None]
    if need:
        now = dt.datetime.now().astimezone()
        for t, frame in _download(need, start).items():
            cached[t], fetched[t] = frame, now
            _write_cache(t, frame)

    found = {t: f for t, f in cached.items() if f is not None and not f.empty}
    if not found:
        raise ProviderError(f"Yahoo Finance returned no prices for: {', '.join(tickers)}. Check the symbols.")
    close = pd.DataFrame({t: f["Close"] for t, f in found.items()})
    volume = pd.DataFrame({t: f["Volume"] for t, f in found.items()})
    prices = _align(close, volume, days, tickers)
    prices.fetched_at = min(fetched[t] for t in prices.tickers) if prices.tickers else None
    return prices


def _cache_path(ticker: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in ticker)
    return CACHE_DIR / f"{safe}.pkl"


def _read_cache(ticker: str, start: dt.date) -> tuple[pd.DataFrame, dt.datetime] | None:
    """The saved frame and when it was downloaded, if that was recent and it reaches back far enough."""
    path = _cache_path(ticker)
    try:
        saved = dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        if dt.datetime.now().astimezone() - saved > CACHE_MAX_AGE:
            return None
        frame = pd.read_pickle(path)
    except Exception:  # noqa: BLE001 - a missing or broken cache file is just a miss
        return None
    if frame.empty or frame.index[0].date() > start + dt.timedelta(days=7):
        return None
    return frame, saved


def _write_cache(ticker: str, frame: pd.DataFrame) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        frame.to_pickle(_cache_path(ticker))
    except OSError as exc:  # the scan still works, it just downloads again next time
        log.warning("Could not cache %s: %s", ticker, exc)


def _download(tickers: list[str], start: dt.date) -> dict[str, pd.DataFrame]:
    """One batch download. Tickers that fail in the batch get one more try, one at a time."""
    import yfinance as yf

    def fetch(batch: list[str], threads: bool) -> dict[str, pd.DataFrame]:
        try:
            raw = yf.download(batch, start=start.isoformat(), auto_adjust=True, progress=False, threads=threads)
        except Exception as exc:  # noqa: BLE001
            if "Rate" in type(exc).__name__ or "Too Many Requests" in str(exc):
                raise ProviderError("Yahoo Finance is rate limiting requests. Wait a minute and try again.", 429) from exc
            raise ProviderError(f"Could not download from Yahoo Finance ({type(exc).__name__}). Check the internet connection.", 502) from exc
        if raw is None or raw.empty:
            return {}
        out = {}
        for t in batch:
            try:
                frame = raw.xs(t, axis=1, level="Ticker")[["Close", "Volume"]].dropna(subset=["Close"])
            except KeyError:
                continue
            if not frame.empty:
                frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
                out[t] = frame
        return out

    got = fetch(tickers, threads=True)
    missing = [t for t in tickers if t not in got]
    if missing:
        got.update(fetch(missing, threads=False))
    return got
