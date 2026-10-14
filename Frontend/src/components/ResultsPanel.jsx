import { useMemo, useState } from 'react';
import LeafChart from './LeafChart.jsx';
import SpreadChart from './SpreadChart.jsx';
import { COLUMNS, DEFAULT_COLUMNS, DETAIL_STATS, asOf, num, price, ticker } from '../format.js';
import { CUSTOM_LABEL } from './ParamBuilder.jsx';

function PairDetail({ row }) {
  const s = row.series;
  const a = ticker(row.a);
  const b = ticker(row.b);
  return (
    <div className="detail">
      <div className="charts">
        <figure>
          <figcaption>Prices, rebased to 100 · the shaded leaf is the gap between them</figcaption>
          <LeafChart a={s.a} b={s.b} dates={s.dates} nameA={a} nameB={b} />
        </figure>
        <figure>
          <figcaption>Spread z-score · the shaded bands are the ±2 entry zone</figcaption>
          <SpreadChart z={s.z} name={`${a} / ${b}`} />
        </figure>
      </div>
      <dl className="stats">
        <div>
          <dt>{a} last price</dt>
          <dd>{price(row.price_a)}</dd>
        </div>
        <div>
          <dt>{b} last price</dt>
          <dd>{price(row.price_b)}</dd>
        </div>
        {DETAIL_STATS.map(([label, key, fmt]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>{fmt(row[key])}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ResultTable({ strategyKey, results }) {
  const cols = COLUMNS[strategyKey] || DEFAULT_COLUMNS;
  const [sort, setSort] = useState({ key: 'score', dir: -1 });
  const [open, setOpen] = useState(() => new Set());

  const rows = useMemo(() => {
    const copy = [...results];
    copy.sort((p, q) => {
      const pv = p[sort.key];
      const qv = q[sort.key];
      if (pv == null) return 1; // missing values always sink
      if (qv == null) return -1;
      return (pv - qv) * sort.dir;
    });
    return copy;
  }, [results, sort]);

  const toggleSort = (key) =>
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === 'score' ? -1 : 1 }));
  const toggleOpen = (id) =>
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const arrow = (key) => (sort.key === key ? (sort.dir === 1 ? ' ↑' : ' ↓') : '');
  const sortHead = (key, label) => (
    <button type="button" className="sort" onClick={() => toggleSort(key)} aria-label={`Sort by ${label}`}>
      {label}{arrow(key)}
    </button>
  );

  return (
    <div className="table" style={{ '--n': cols.length }}>
      <div className="thead">
        <span className="c-glyph" />
        <span className="c-pair">Pair</span>
        {cols.map((c) => (
          <span key={c.key} className="c-stat">{sortHead(c.key, c.label)}</span>
        ))}
        <span className="c-score">{sortHead('score', 'Fit')}</span>
      </div>

      <ul>
        {rows.map((row, i) => {
          const id = `${row.a}-${row.b}`;
          const isOpen = open.has(id);
          return (
            <li key={id} className={isOpen ? 'pair open' : 'pair'}>
              <button
                type="button"
                className="row"
                aria-expanded={isOpen}
                aria-controls={`detail-${id}`}
                onClick={() => toggleOpen(id)}
              >
                <span className="c-glyph">
                  <LeafChart
                    mini
                    order={i}
                    a={row.series.a}
                    b={row.series.b}
                    dates={row.series.dates}
                    nameA={ticker(row.a)}
                    nameB={ticker(row.b)}
                  />
                </span>
                <span className="c-pair">
                  <strong title={row.a}>{ticker(row.a)}</strong>
                  <i aria-hidden="true">/</i>
                  <strong title={row.b}>{ticker(row.b)}</strong>
                  {row.price_a != null && (
                    <small className="px">
                      {price(row.price_a)} / {price(row.price_b)}
                    </small>
                  )}
                </span>
                {cols.map((c) => {
                  const v = row[c.key];
                  const hot = c.signal && v != null && Math.abs(v) >= 2;
                  return (
                    <span key={c.key} className={hot ? 'c-stat hot' : 'c-stat'}>
                      <em className="lbl">{c.label}</em>
                      {c.fmt(v)}
                      {hot && <small>entry zone</small>}
                    </span>
                  );
                })}
                <span className="c-score">
                  <span className="fit" aria-hidden="true">
                    <span style={{ width: `${Math.min(100, row.score)}%` }} />
                  </span>
                  <b>{num(row.score, 0)}</b>
                </span>
              </button>
              {isOpen && (
                <div id={`detail-${id}`}>
                  <PairDetail row={row} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function ResultsPanel({ scan, strategies }) {
  const [active, setActive] = useState(null);

  if (scan.status === 'idle') {
    return (
      <section className="empty">
        <h2>Choose a strategy, then find pairs</h2>
        <p>
          Leaf screens every pair in your universe for correlation, cointegration and how fast the
          spread snaps back, then keeps the pairs that fit each strategy you picked.
        </p>
      </section>
    );
  }
  if (scan.status === 'loading') {
    return (
      <section className="empty" aria-live="polite">
        <h2>Screening pairs…</h2>
        <p>Running cointegration tests across the universe. Larger universes take longer.</p>
      </section>
    );
  }
  if (scan.status === 'error') {
    return (
      <section className="empty error" role="alert">
        <h2>The scan did not finish</h2>
        <p>{scan.error}</p>
      </section>
    );
  }

  const { data } = scan;
  const keys = Object.keys(data.strategies);
  const current = keys.includes(active) ? active : keys[0];
  const block = data.strategies[current];
  const label = (k) => strategies[k]?.label || CUSTOM_LABEL;

  return (
    <section className="results">
      {data.as_of && <p className="as-of">{asOf(data.as_of)}</p>}
      <p className="meta">
        {data.universe_size} tickers · {data.pairs_screened} pairs passed the correlation prefilter
        {data.dropped?.length > 0 && ` · no usable data for ${data.dropped.join(', ')}`}
      </p>
      {data.sample && (
        <p className="sample-note">Sample data. Results are examples, not live prices.</p>
      )}

      <div className="tabs" role="tablist" aria-label="Strategy results">
        {keys.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            id={`tab-${k}`}
            aria-selected={k === current}
            aria-controls="tabpanel"
            className={k === current ? 'tab on' : 'tab'}
            onClick={() => setActive(k)}
          >
            {label(k)}
            <span className="count">{data.strategies[k].results.length}</span>
          </button>
        ))}
      </div>

      <div id="tabpanel" role="tabpanel" aria-labelledby={`tab-${current}`}>
        {block.results.length === 0 ? (
          <div className="none">
            <h2>No pairs fit {label(current).toLowerCase()}</h2>
            <p>
              Nothing in the universe meets the requirements over this window. Try a longer
              lookback.
            </p>
          </div>
        ) : (
          <>
            <ResultTable key={current} strategyKey={current} results={block.results} />
            <div className="reading">
              <h3>Reading of these pairs</h3>
              <p>{block.explanation}</p>
            </div>
          </>
        )}
      </div>

      <p className="fine">
        Statistics are in-sample and ignore trading costs. Treat this as research, not advice.
      </p>
    </section>
  );
}