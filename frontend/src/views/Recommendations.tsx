import { useMemo, useState } from 'react';
import type { Fleet } from '../types/fleet';
import { allFindings, fmtMoney, num, severityColor, severityRank } from '../lib/fleet';
import { CategoryBadge, SeverityBadge } from '../components/Badges';

export function Recommendations({ fleet }: { fleet: Fleet }) {
  const findings = useMemo(() => allFindings(fleet), [fleet]);
  const [catFilter, setCatFilter] = useState('');
  const [sevFilter, setSevFilter] = useState('');

  const categories = useMemo(
    () => [...new Set(findings.map((f) => f.category ?? 'unknown'))].sort(),
    [findings],
  );
  const severities = useMemo(
    () =>
      [...new Set(findings.map((f) => f.severity ?? 'info'))].sort(
        (a, b) => severityRank(a) - severityRank(b),
      ),
    [findings],
  );

  const filtered = useMemo(
    () =>
      findings.filter((f) => {
        if (catFilter && (f.category ?? 'unknown') !== catFilter) return false;
        if (sevFilter && (f.severity ?? 'info') !== sevFilter) return false;
        return true;
      }),
    [findings, catFilter, sevFilter],
  );

  const totalSavings = useMemo(
    () => filtered.reduce((s, f) => s + num(f.estimated_monthly_savings_usd), 0),
    [filtered],
  );

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Recommendations</h1>
          <div className="sub">{filtered.length} findings across the fleet</div>
        </div>
        <div className="stat" style={{ minWidth: 220 }}>
          <div className="label">Potential monthly savings</div>
          <div className="value good">{fmtMoney(totalSavings)}</div>
          <div className="sub">sum of shown findings</div>
        </div>
      </div>

      <div className="filters">
        <select className="select" value={sevFilter} onChange={(e) => setSevFilter(e.target.value)}>
          <option value="">All severities</option>
          {severities.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select className="select" value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {filtered.map((f, i) => (
        <div
          className="finding"
          key={`${f.nodeId}-${f.id}-${i}`}
          style={{ borderLeftColor: severityColor(f.severity) }}
        >
          <div className="f-head">
            <SeverityBadge severity={f.severity} />
            <CategoryBadge category={f.category} />
            <span className="f-title">{f.title}</span>
            <span className="pill">{f.nodeName}</span>
            {num(f.estimated_monthly_savings_usd) > 0 && (
              <span className="f-save">{fmtMoney(f.estimated_monthly_savings_usd)}/mo</span>
            )}
          </div>
          {f.detail && <div className="f-rec">{f.detail}</div>}
          {f.recommendation && (
            <div className="f-rec">
              <strong>Recommendation:</strong> {f.recommendation}
            </div>
          )}
        </div>
      ))}

      {filtered.length === 0 && (
        <div className="card empty">No findings match the current filters.</div>
      )}
    </div>
  );
}
