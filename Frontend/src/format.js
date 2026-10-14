const dash = '–';

export const num = (v, d = 2) => (v == null ? dash : Number(v).toFixed(d));
export const pval = (v) => (v == null ? dash : v < 0.001 ? '<0.001' : Number(v).toFixed(3));
export const days = (v) => (v == null ? 'never' : v >= 100 ? '100+ d' : `${Number(v).toFixed(1)} d`);
export const signed = (v) => (v == null ? dash : `${v > 0 ? '+' : ''}${Number(v).toFixed(2)}`);
export const percent = (v) => (v == null ? dash : `${Math.round(v * 100)}%`);

// Yahoo's symbols carry suffixes that only make sense to Yahoo. On screen: BTC-USD is BTC,
// UNI7083-USD is UNI, EURUSD=X is EURUSD, and futures (GC=F) get their plain name.
const FUTURES = {
  GC: 'Gold', SI: 'Silver', PL: 'Platinum', PA: 'Palladium', HG: 'Copper',
  CL: 'WTI crude', BZ: 'Brent', NG: 'Nat gas', HO: 'Heating oil', RB: 'Gasoline',
  ZC: 'Corn', ZW: 'Wheat', KE: 'KC wheat', ZS: 'Soybeans', ZM: 'Soy meal', ZL: 'Soy oil', ZO: 'Oats',
  KC: 'Coffee', SB: 'Sugar', CC: 'Cocoa', CT: 'Cotton', OJ: 'Orange juice',
  LE: 'Live cattle', GF: 'Feeder cattle', HE: 'Lean hogs',
};

export function ticker(symbol) {
  if (symbol.endsWith('=F')) return FUTURES[symbol.slice(0, -2)] || symbol.slice(0, -2);
  if (symbol.endsWith('=X')) return symbol.slice(0, -2);
  if (symbol.endsWith('-USD')) return symbol.slice(0, -4).replace(/\d+$/, '');
  return symbol;
}

// Prices run from 0.00001 (SHIB) to 100,000 (BTC), and forex rates need four decimals.
export const price = (v) =>
  v == null
    ? dash
    : v >= 1000
      ? v.toLocaleString(undefined, { maximumFractionDigits: 2 })
      : v >= 10
        ? v.toFixed(2)
        : v.toLocaleString(undefined, { maximumSignificantDigits: 5 });

const dayLabel = (d) => d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });

/**
 * "Prices as of 11:20 AM, Mon Oct 12", or the latest close date when it is older than the fetch
 * day (a weekend or holiday). Crypto and forex bars are dated in UTC, so late in the evening their
 * date can be the day after the local fetch day; that still counts as current.
 */
export function asOf({ date, fetched_at: fetchedAt }) {
  const close = new Date(`${date}T00:00:00`);
  if (!fetchedAt) return `Latest close ${dayLabel(close)}`;
  const fetched = new Date(fetchedAt);
  const fetchedDay = new Date(fetched.getFullYear(), fetched.getMonth(), fetched.getDate());
  const time = fetched.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  return close < fetchedDay
    ? `Latest close ${dayLabel(close)} · checked ${time}, ${dayLabel(fetched)}`
    : `Prices as of ${time}, ${dayLabel(fetched)}`;
}

export const monthYear = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: 'short', year: 'numeric' });

// Plain names for the requirement keys.
export const REQ_LABELS = {
  coint_p: 'Cointegration p',
  half_life: 'Half-life',
  corr: 'Correlation',
  hedge_effectiveness: 'Variance cut',
};

export const prettyReq = (s) => s.replace('<=', '≤').replace('>=', '≥');

// Which numbers matter most for each strategy, in reading order (used by the screener table).
export const COLUMNS = {
  mean_reversion: [
    { key: 'coint_p', label: 'Coint. p', fmt: pval },
    { key: 'half_life', label: 'Half-life', fmt: days },
    { key: 'zscore', label: 'Z now', fmt: signed, signal: true },
  ],
  arbitrage: [
    { key: 'coint_p', label: 'Coint. p', fmt: pval },
    { key: 'half_life', label: 'Half-life', fmt: days },
    { key: 'corr', label: 'Corr', fmt: (v) => num(v, 2) },
  ],
  hedging: [
    { key: 'corr', label: 'Corr', fmt: (v) => num(v, 2) },
    { key: 'return_beta', label: 'Hedge ratio', fmt: (v) => num(v, 2) },
    { key: 'hedge_effectiveness', label: 'Variance cut', fmt: percent },
  ],
};

export const DEFAULT_COLUMNS = [
  { key: 'corr', label: 'Corr', fmt: (v) => num(v, 2) },
  { key: 'coint_p', label: 'Coint. p', fmt: pval },
  { key: 'half_life', label: 'Half-life', fmt: days },
  { key: 'zscore', label: 'Z now', fmt: signed, signal: true },
];

// Every statistic shown in a pair's detail panel.
export const DETAIL_STATS = [
  ['Correlation (daily returns)', 'corr', (v) => num(v, 3)],
  ['Cointegration p-value', 'coint_p', pval],
  ['Half-life of the spread', 'half_life', days],
  ['Z-score now', 'zscore', signed],
  ['Hedge ratio (log prices)', 'hedge_ratio', (v) => num(v, 3)],
  ['Hedge ratio (returns)', 'return_beta', (v) => num(v, 3)],
  ['Variance cut by hedging', 'hedge_effectiveness', percent],
  ['Spread std (log)', 'spread_std', (v) => num(v, 4)],
  ['Volatility, first name', 'vol_a', percent],
  ['Volatility, second name', 'vol_b', percent],
];