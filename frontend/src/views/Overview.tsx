import { useMemo } from 'react';
import type { Fleet } from '../types/fleet';
import { computeTotals, fmtMoney, fmtNum, providerColor } from '../lib/fleet';
import { PowerBadge } from '../components/Badges';

export function Overview({ fleet }: { fleet: Fleet }) {
  const totals = useMemo(() => computeTotals(fleet), [fleet]);
  const maxProvCost = Math.max(1, ...totals.byProvider.map((p) => p.monthly));
  const savingsPct = totals.currentMonthly > 0 ? (totals.savings / totals.currentMonthly) * 100 : 0;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Fleet overview</h1>
          <div className="sub">A snapshot of the entire environment</div>
        </div>
      </div>

      <div className="grid stat-grid">
        <div className="stat">
          <div className="label">Nodes</div>
          <div className="value">{totals.nodeCount}</div>
        </div>
        <div className="stat">
          <div className="label">Total vCPUs</div>
          <div className="value">{fmtNum(totals.vcpus)}</div>
        </div>
        <div className="stat">
          <div className="label">Total RAM</div>
          <div className="value">
            {fmtNum(totals.ramGb)} <span className="sub" style={{ fontSize: 14 }}>GB</span>
          </div>
        </div>
        <div className="stat">
          <div className="label">Total storage</div>
          <div className="value">
            {fmtNum(totals.storageGb)} <span className="sub" style={{ fontSize: 14 }}>GB</span>
          </div>
        </div>
        <div className="stat">
          <div className="label">Current monthly</div>
          <div className="value">{fmtMoney(totals.currentMonthly)}</div>
          <div className="sub">summed current-platform cost</div>
        </div>
        <div className="stat">
          <div className="label">Potential savings</div>
          <div className="value good">{fmtMoney(totals.savings)}</div>
          <div className="sub">
            cheapest mix {fmtMoney(totals.cheapestMonthly)} ({savingsPct.toFixed(0)}% off)
          </div>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>Spend by provider</h3>
          {totals.byProvider.map((p) => (
            <div className="bar-row" key={p.key}>
              <span className="nowrap">{p.key}</span>
              <span className="bar-track">
                <span
                  className="bar-fill"
                  style={{
                    width: `${(p.monthly / maxProvCost) * 100}%`,
                    background: providerColor(p.key),
                  }}
                />
              </span>
              <span className="num">{fmtMoney(p.monthly)}</span>
            </div>
          ))}
        </div>

        <div className="card">
          <h3>Capacity by provider</h3>
          <table className="mini-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th className="num">Nodes</th>
                <th className="num">vCPU</th>
                <th className="num">RAM GB</th>
              </tr>
            </thead>
            <tbody>
              {totals.byProvider.map((p) => (
                <tr key={p.key}>
                  <td>{p.key}</td>
                  <td className="num">{p.count}</td>
                  <td className="num">{fmtNum(p.vcpus)}</td>
                  <td className="num">{fmtNum(p.ramGb)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>Power state</h3>
          <div className="chips">
            {totals.byPowerState.map((s) => (
              <span key={s.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <PowerBadge state={s.key} />
                <span className="muted">x {s.count}</span>
              </span>
            ))}
          </div>
        </div>
        <div className="card">
          <h3>Node kind</h3>
          <div className="chips">
            {totals.byKind.map((k) => (
              <span key={k.key} className="pill">
                {k.key} x {k.count}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
