// Derivation helpers over a Fleet snapshot. Pure functions, no React.

import type { CostEstimate, Endpoint, Finding, Fleet, Node } from '../types/fleet';

export const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

export function num(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0;
}

export function fmtMoney(v: number | null | undefined): string {
  const n = num(v);
  return n.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: n !== 0 && Math.abs(n) < 100 ? 2 : 0,
  });
}

export function fmtNum(v: number | null | undefined): string {
  return num(v).toLocaleString('en-US', { maximumFractionDigits: 1 });
}

/** RAM in GB derived from memory_mb. */
export function ramGb(node: Node): number {
  return num(node.compute?.memory_mb) / 1024;
}

/** The platform a node runs on — source.provider is authoritative, placement is a fallback. */
export function provider(node: Node): string {
  return (node.source?.provider || node.placement?.provider || 'unknown').toString();
}

export function powerState(node: Node): string {
  return (node.power_state ?? 'unknown').toString();
}

/** First IP across NICs (mirrors the model's Node.primary_ip). */
export function primaryIp(node: Node): string | undefined {
  for (const nic of node.nics ?? []) {
    if (nic.ips && nic.ips.length > 0) return nic.ips[0];
  }
  return undefined;
}

export function osLabel(node: Node): string {
  const os = node.os;
  if (!os) return '-';
  if (os.distro) return os.distro;
  if (os.family && os.family !== 'unknown') {
    return os.version ? `${os.family} ${os.version}` : os.family;
  }
  return '-';
}

export function storageGb(node: Node): number {
  return (node.disks ?? []).reduce((s, d) => s + num(d.size_gb), 0);
}

/** The cost estimate marked current (or matching the node's provider, else first). */
export function currentCost(node: Node): CostEstimate | undefined {
  const estimates = node.analysis?.cost_estimates ?? [];
  const flagged = estimates.find((c) => c.is_current);
  if (flagged) return flagged;
  const prov = provider(node);
  return estimates.find((c) => (c.platform ?? '').toLowerCase() === prov.toLowerCase()) ?? estimates[0];
}

/** Cheapest of all priced estimates (including current). */
export function cheapestOverall(node: Node): CostEstimate | undefined {
  const priced = (node.analysis?.cost_estimates ?? []).filter((c) => c.monthly_usd != null);
  if (priced.length === 0) return undefined;
  return priced.reduce((best, c) => (num(c.monthly_usd) < num(best.monthly_usd) ? c : best));
}

export interface FleetTotals {
  nodeCount: number;
  vcpus: number;
  ramGb: number;
  storageGb: number;
  currentMonthly: number;
  cheapestMonthly: number;
  savings: number;
  byProvider: Array<{ key: string; count: number; vcpus: number; ramGb: number; monthly: number }>;
  byPowerState: Array<{ key: string; count: number }>;
  byKind: Array<{ key: string; count: number }>;
}

export function computeTotals(fleet: Fleet): FleetTotals {
  const nodes = fleet.nodes ?? [];
  const byProvider = new Map<
    string,
    { key: string; count: number; vcpus: number; ramGb: number; monthly: number }
  >();
  const byPower = new Map<string, number>();
  const byKind = new Map<string, number>();

  let vcpus = 0;
  let ram = 0;
  let storage = 0;
  let currentMonthly = 0;
  let cheapestMonthly = 0;

  for (const node of nodes) {
    const nodeVcpus = num(node.compute?.vcpus);
    const nodeRam = ramGb(node);
    vcpus += nodeVcpus;
    ram += nodeRam;
    storage += storageGb(node);

    const cur = num(currentCost(node)?.monthly_usd);
    const cheap = num((cheapestOverall(node) ?? currentCost(node))?.monthly_usd);
    currentMonthly += cur;
    cheapestMonthly += cheap;

    const prov = provider(node);
    const p = byProvider.get(prov) ?? { key: prov, count: 0, vcpus: 0, ramGb: 0, monthly: 0 };
    p.count += 1;
    p.vcpus += nodeVcpus;
    p.ramGb += nodeRam;
    p.monthly += cur;
    byProvider.set(prov, p);

    byPower.set(powerState(node), (byPower.get(powerState(node)) ?? 0) + 1);
    const kind = (node.kind ?? 'unknown').toString();
    byKind.set(kind, (byKind.get(kind) ?? 0) + 1);
  }

  return {
    nodeCount: nodes.length,
    vcpus,
    ramGb: ram,
    storageGb: storage,
    currentMonthly,
    cheapestMonthly,
    savings: Math.max(0, currentMonthly - cheapestMonthly),
    byProvider: [...byProvider.values()].sort((a, b) => b.monthly - a.monthly || b.count - a.count),
    byPowerState: [...byPower.entries()]
      .map(([key, count]) => ({ key, count }))
      .sort((a, b) => b.count - a.count),
    byKind: [...byKind.entries()]
      .map(([key, count]) => ({ key, count }))
      .sort((a, b) => b.count - a.count),
  };
}

export function endpointLabel(ep: Endpoint | undefined, index: Record<string, Node>): string {
  if (!ep) return 'unknown';
  if (ep.node_id) {
    const n = index[ep.node_id];
    const base = n ? n.name : ep.node_id;
    return ep.port ? `${base}:${ep.port}` : base;
  }
  if (ep.label) return ep.label;
  const base = ep.address || 'external';
  return ep.port ? `${base}:${ep.port}` : base;
}

export function mechanismLabel(m: string): string {
  return (m || 'unknown').replace(/_/g, ' ');
}

export interface FlattenedFinding extends Finding {
  nodeId: string;
  nodeName: string;
}

export function allFindings(fleet: Fleet): FlattenedFinding[] {
  const out: FlattenedFinding[] = [];
  for (const node of fleet.nodes ?? []) {
    for (const f of node.analysis?.findings ?? []) {
      out.push({ ...f, nodeId: node.id, nodeName: node.name });
    }
  }
  return out.sort((a, b) => {
    const s = num(b.estimated_monthly_savings_usd) - num(a.estimated_monthly_savings_usd);
    if (s !== 0) return s;
    return severityRank(a.severity) - severityRank(b.severity);
  });
}

export function severityRank(s: string | undefined): number {
  return SEVERITY_ORDER[(s ?? 'info').toString()] ?? 99;
}

// ---- Flow graph ----

export interface GraphNode {
  id: string;
  label: string;
  provider: string;
  powerState: string;
  external: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  mechanism: string;
  direction: string;
  detail: string;
}

export function buildGraph(fleet: Fleet): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  const fleetIds = new Set((fleet.nodes ?? []).map((n) => n.id));

  for (const n of fleet.nodes ?? []) {
    nodes.set(n.id, {
      id: n.id,
      label: n.name,
      provider: provider(n),
      powerState: powerState(n),
      external: false,
    });
  }

  const ensureExternal = (ep: Endpoint): string | undefined => {
    if (ep.node_id && fleetIds.has(ep.node_id)) return ep.node_id;
    const key = ep.node_id || ep.address || ep.label;
    if (!key) return undefined;
    const extId = `ext:${key}`;
    if (!nodes.has(extId)) {
      nodes.set(extId, {
        id: extId,
        label: ep.label || ep.address || ep.node_id || 'external',
        provider: 'external',
        powerState: 'external',
        external: true,
      });
    }
    return extId;
  };

  let i = 0;
  for (const n of fleet.nodes ?? []) {
    for (const flow of n.flows ?? []) {
      const peerId = ensureExternal(flow.peer);
      if (!peerId) continue;
      const mechanism = (flow.mechanism || 'unknown').toString();
      // A flow originates from the owning node; direction tells us which way data moves.
      const inbound = flow.direction === 'inbound';
      const src = inbound ? peerId : n.id;
      const tgt = inbound ? n.id : peerId;
      edges.push({
        id: `e${i++}`,
        source: src,
        target: tgt,
        label: mechanismLabel(mechanism),
        mechanism,
        direction: (flow.direction || 'outbound').toString(),
        detail: flow.detail || '',
      });
    }
  }

  return { nodes: [...nodes.values()], edges };
}

export function nodeIndex(fleet: Fleet): Record<string, Node> {
  const idx: Record<string, Node> = {};
  for (const n of fleet.nodes ?? []) idx[n.id] = n;
  return idx;
}

// ---- Colors ----

export function providerColor(p: string): string {
  const map: Record<string, string> = {
    aws: '#ff9900',
    gcp: '#4285f4',
    vmware: '#607078',
    proxmox: '#e57000',
    external: '#6b7280',
    unknown: '#7c8794',
  };
  return map[p.toLowerCase()] ?? '#a78bfa';
}

export function severityColor(s: string | undefined): string {
  const map: Record<string, string> = {
    critical: '#ef4444',
    high: '#f97316',
    medium: '#eab308',
    low: '#3b82f6',
    info: '#6b7280',
  };
  return map[(s ?? 'info').toLowerCase()] ?? '#6b7280';
}
