import { useMemo, useState } from 'react';
import type { Fleet, Node } from '../types/fleet';
import {
  currentCost,
  fmtMoney,
  fmtNum,
  num,
  osLabel,
  powerState,
  primaryIp,
  provider,
  ramGb,
} from '../lib/fleet';
import { PowerBadge, ProviderBadge } from '../components/Badges';
import { NodeDrawer } from './NodeDrawer';

type SortKey =
  | 'name'
  | 'provider'
  | 'kind'
  | 'power'
  | 'vcpus'
  | 'ram'
  | 'os'
  | 'ip'
  | 'cost';

interface Row {
  node: Node;
  name: string;
  provider: string;
  kind: string;
  power: string;
  vcpus: number;
  ram: number;
  os: string;
  ip: string;
  cost: number;
}

export function Nodes({ fleet }: { fleet: Fleet }) {
  const [selected, setSelected] = useState<Node | null>(null);
  const [query, setQuery] = useState('');
  const [provFilter, setProvFilter] = useState('');
  const [powerFilter, setPowerFilter] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('cost');
  const [asc, setAsc] = useState(false);

  const rows: Row[] = useMemo(
    () =>
      (fleet.nodes ?? []).map((node) => ({
        node,
        name: node.name,
        provider: provider(node),
        kind: (node.kind ?? 'unknown').toString(),
        power: powerState(node),
        vcpus: num(node.compute?.vcpus),
        ram: ramGb(node),
        os: osLabel(node),
        ip: primaryIp(node) ?? '-',
        cost: num(currentCost(node)?.monthly_usd),
      })),
    [fleet],
  );

  const providers = useMemo(() => [...new Set(rows.map((r) => r.provider))].sort(), [rows]);
  const powers = useMemo(() => [...new Set(rows.map((r) => r.power))].sort(), [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = rows.filter((r) => {
      if (provFilter && r.provider !== provFilter) return false;
      if (powerFilter && r.power !== powerFilter) return false;
      if (q && !`${r.name} ${r.os} ${r.ip} ${r.kind}`.toLowerCase().includes(q)) return false;
      return true;
    });
    out.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      let cmp: number;
      if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv;
      else cmp = String(av).localeCompare(String(bv));
      return asc ? cmp : -cmp;
    });
    return out;
  }, [rows, query, provFilter, powerFilter, sortKey, asc]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(key === 'name' || key === 'provider' || key === 'os' || key === 'kind');
    }
  };

  const header = (key: SortKey, label: string, cls = '') => (
    <th className={cls} onClick={() => toggleSort(key)}>
      {label}
      {sortKey === key && <span className="sort-ind">{asc ? '^' : 'v'}</span>}
    </th>
  );

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Nodes</h1>
          <div className="sub">
            {filtered.length} of {rows.length} nodes - click a row for full detail
          </div>
        </div>
      </div>

      <div className="filters">
        <input
          className="input"
          placeholder="Search name / OS / IP..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ minWidth: 240 }}
        />
        <select className="select" value={provFilter} onChange={(e) => setProvFilter(e.target.value)}>
          <option value="">All providers</option>
          {providers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select className="select" value={powerFilter} onChange={(e) => setPowerFilter(e.target.value)}>
          <option value="">All power states</option>
          {powers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              {header('name', 'Name')}
              {header('provider', 'Provider')}
              {header('kind', 'Kind')}
              {header('power', 'Power')}
              {header('vcpus', 'vCPU', 'num')}
              {header('ram', 'RAM GB', 'num')}
              {header('os', 'OS')}
              {header('ip', 'Primary IP')}
              {header('cost', 'Monthly', 'num')}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.node.id} onClick={() => setSelected(r.node)}>
                <td style={{ fontWeight: 600 }}>{r.name}</td>
                <td>
                  <ProviderBadge provider={r.provider} />
                </td>
                <td>{r.kind}</td>
                <td>
                  <PowerBadge state={r.power} />
                </td>
                <td className="num">{fmtNum(r.vcpus)}</td>
                <td className="num">{fmtNum(r.ram)}</td>
                <td>{r.os}</td>
                <td className="muted">{r.ip}</td>
                <td className="num">{r.cost > 0 ? fmtMoney(r.cost) : '-'}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="empty" style={{ textAlign: 'center', padding: 24 }}>
                  No nodes match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <NodeDrawer node={selected} fleet={fleet} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
