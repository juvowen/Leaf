import { useState } from 'react';

// Trading days per period (about 21 a month). `info` is what the (i) next to each one says.
export const PERIODS = [
  {
    days: 21,
    label: '1M',
    name: '1 month',
    info: 'About 21 trading days. Enough to see what moved together recently, but cointegration and half-life are not reliable this short: there are too few points, and a spread that takes weeks to revert has no room to show it.',
  },
  {
    days: 63,
    label: '3M',
    name: '3 months',
    info: 'About 63 trading days. Correlation is usable, but cointegration can still flip from one month to the next. Treat matches as leads to check on a longer window.',
  },
  {
    days: 126,
    label: '6M',
    name: '6 months',
    info: 'About 126 trading days. The shortest window where cointegration and half-life start to hold up. Weighted toward how pairs behave lately.',
  },
  {
    days: 252,
    label: '1Y',
    name: '1 year',
    info: 'About 252 trading days. A good balance: enough data for stable tests, and recent enough to reflect how pairs trade now.',
  },
  {
    days: 756,
    label: '3Y',
    name: '3 years',
    info: 'About 756 trading days. The most reliable tests and usually the most mean-reversion matches, but a relationship that broke down recently can still pass on its long history.',
  },
];

export default function ScanControls({ source, days, onDays, onScan, busy, selectedCount }) {
  const disabled = busy || selectedCount === 0;
  const [peek, setPeek] = useState(null); // shown while hovering or focusing an (i)
  const [pinned, setPinned] = useState(null); // shown after clicking an (i), until clicked again
  const shown = PERIODS.find((p) => p.days === (peek ?? pinned));

  return (
    <form
      className="controls"
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled) onScan();
      }}
    >
      <p className="source">{source}</p>

      <fieldset className="field periods">
        <legend>Lookback</legend>
        <div className="period-row">
          {PERIODS.map((p) => (
            <div key={p.days} className={p.days === days ? 'period on' : 'period'}>
              <label>
                <input
                  type="radio"
                  name="period"
                  value={p.days}
                  checked={p.days === days}
                  onChange={() => onDays(p.days)}
                />
                <span title={p.name}>{p.label}</span>
              </label>
              <button
                type="button"
                className="info"
                aria-label={`What ${p.name} means for the results`}
                aria-expanded={shown?.days === p.days}
                aria-controls="period-info"
                onClick={() => setPinned((cur) => (cur === p.days ? null : p.days))}
                onMouseEnter={() => setPeek(p.days)}
                onMouseLeave={() => setPeek(null)}
                onFocus={() => setPeek(p.days)}
                onBlur={() => setPeek(null)}
                onKeyDown={(e) => e.key === 'Escape' && (setPinned(null), setPeek(null))}
              >
                i
              </button>
            </div>
          ))}
        </div>
        <p id="period-info" className="period-info" aria-live="polite" hidden={!shown}>
          {shown && (
            <>
              <strong>{shown.name}.</strong> {shown.info}
            </>
          )}
        </p>
      </fieldset>

      <button type="submit" className="primary" disabled={disabled}>
        {busy ? 'Scanning…' : selectedCount === 0 ? 'Pick a strategy or a parameter' : 'Find pairs'}
      </button>
    </form>
  );
}
