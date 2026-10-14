import { useRef, useState } from 'react';
import { scanMulti } from '../api.js';
import StrategyList from '../components/StrategyList.jsx';
import ScanControls from '../components/ScanControls.jsx';
import ResultsPanel from '../components/ResultsPanel.jsx';
import ParamBuilder, { CUSTOM_KEY, toSpec } from '../components/ParamBuilder.jsx';
import AssetTabs, { ASSET_CLASSES, PANEL_ID, tabId } from '../components/AssetTabs.jsx';
import { logExSpec } from '../ex.js';

export default function Screener({ strategies, query }) {
  // Nothing is ticked on arrival, unless a link names a strategy (#/screener?s=hedging).
  const initial = (query.s || '').split(',').filter(Boolean);
  const [selected, setSelected] = useState(() => new Set(initial));
  // A link can open a market directly (#/screener?a=crypto).
  const [asset, setAsset] = useState(() => (ASSET_CLASSES.some((a) => a.key === query.a) ? query.a : 'stock'));
  const [days, setDays] = useState(252); // 1Y, see PERIODS in ScanControls
  const [params, setParams] = useState({}); // parameter key -> slider value, for the ones ticked
  const [scan, setScan] = useState({ status: 'idle' });
  const resultsRef = useRef(null);

  const chosen = strategies ? [...selected].filter((k) => strategies[k]) : [];
  const custom = toSpec(params);

  const toggle = (key) => {
    // Ticking a card (not un-ticking) asks EX what Lego will need for it.
    if (!selected.has(key) && strategies?.[key]) logExSpec(key, strategies[key]);
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  // Results belong to one market, so switching markets clears them.
  const switchAsset = (key) => {
    if (key === asset) return;
    setAsset(key);
    setScan({ status: 'idle' });
  };

  const run = async () => {
    setScan({ status: 'loading' });
    // On narrow screens the controls sit above the results, so bring the results into view.
    if (window.matchMedia('(max-width: 960px)').matches) {
      const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      resultsRef.current?.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'start' });
    }
    try {
      // Real prices only, over the backend's built-in universe for this market. Your own parameters ride along
      // as one more strategy, with its spec spelled out.
      const data = await scanMulti({
        strategies: custom ? [...chosen, CUSTOM_KEY] : chosen,
        specs: custom ? { [CUSTOM_KEY]: custom } : undefined,
        provider: 'yahoo',
        asset_class: asset,
        days,
      });
      setScan({ status: 'done', data });
    } catch (e) {
      setScan({ status: 'error', error: e.message });
    }
  };

  return (
    <div className="screener">
      <header className="wrap page-head">
        <h1>Screener</h1>
        <p>Pick one or more strategies, or set your own parameters, and Leaf returns the pairs that fit.</p>
      </header>

      {strategies && (
        <div className="wrap">
          <AssetTabs value={asset} onChange={switchAsset} />
        </div>
      )}

      {strategies && (
        <div className="wrap workspace" id={PANEL_ID} role="tabpanel" aria-labelledby={tabId(asset)}>
          <aside className="controls-col" aria-label="Scan setup">
            <h2>Strategies</h2>
            <StrategyList strategies={strategies} selected={new Set(chosen)} onToggle={toggle} />

            <h2>Your own parameters</h2>
            <p className="source">Skip the strategies and screen on the numbers directly.</p>
            <ParamBuilder values={params} onChange={setParams} />

            <h2>Data</h2>
            <ScanControls
              source={ASSET_CLASSES.find((a) => a.key === asset).source}
              days={days}
              onDays={setDays}
              onScan={run}
              busy={scan.status === 'loading'}
              selectedCount={chosen.length + (custom ? 1 : 0)}
            />
          </aside>

          <div className="results-col" ref={resultsRef}>
            <ResultsPanel scan={scan} strategies={strategies} />
          </div>
        </div>
      )}
    </div>
  );
}