// The markets a scan can cover. `key` is the backend's asset_class, `source` is what the
// Data section says about the built-in list for that market.
export const ASSET_CLASSES = [
  { key: 'stock', label: 'Stocks', source: 'Daily prices from Yahoo Finance, across about 125 US stocks and equity funds.' },
  { key: 'crypto', label: 'Crypto', source: 'Daily prices from Yahoo Finance, across about 30 coins priced in dollars. Crypto trades every day, so a period covers more days.' },
  { key: 'forex', label: 'Forex', source: 'Daily rates from Yahoo Finance, across major and cross currency pairs plus currency funds.' },
  { key: 'commodity', label: 'Commodities', source: 'Daily prices from Yahoo Finance, across metal, energy, grain and livestock futures and the funds that hold them.' },
  { key: 'mix', label: 'Mix', source: 'Daily prices from Yahoo Finance, across a selection from every market. Only pairs that cross markets are screened, like oil stocks against crude or the yen against gold. Weekdays only, so crypto weekends roll into Monday.' },
];

// Short names for the market tags on mixed pairs.
export const MARKET_TAGS = { stock: 'Stock', crypto: 'Crypto', forex: 'FX', commodity: 'Commodity' };

export const PANEL_ID = 'asset-panel';
export const tabId = (key) => `asset-tab-${key}`;

// Tabs follow the ARIA pattern: one tab stop, arrow keys move between markets.
export default function AssetTabs({ value, onChange }) {
  const move = (e) => {
    const i = ASSET_CLASSES.findIndex((a) => a.key === value);
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    let next;
    if (step) next = ASSET_CLASSES[(i + step + ASSET_CLASSES.length) % ASSET_CLASSES.length];
    else if (e.key === 'Home') next = ASSET_CLASSES[0];
    else if (e.key === 'End') next = ASSET_CLASSES[ASSET_CLASSES.length - 1];
    if (!next) return;
    e.preventDefault();
    onChange(next.key);
    document.getElementById(tabId(next.key))?.focus();
  };

  return (
    <div className="asset-tabs" role="tablist" aria-label="Market" onKeyDown={move}>
      {ASSET_CLASSES.map((a) => (
        <button
          key={a.key}
          id={tabId(a.key)}
          type="button"
          role="tab"
          aria-selected={a.key === value}
          aria-controls={PANEL_ID}
          tabIndex={a.key === value ? 0 : -1}
          className={a.key === value ? 'asset-tab on' : 'asset-tab'}
          onClick={() => onChange(a.key)}
        >
          {a.label}
        </button>
      ))}
    </div>
  );
}
