import type { ReactNode } from 'react';
import type { Fleet, Node } from '../types/fleet';
import {
  cheapestOverall,
  currentCost,
  endpointLabel,
  fmtMoney,
  fmtNum,
  mechanismLabel,
  num,
  nodeIndex,
  ramGb,
  severityColor,
} from '../lib/fleet';
import { CategoryBadge, PowerBadge, ProviderBadge, SeverityBadge } from '../components/Badges';

function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

function SubBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="muted" style={{ fontSize: 12, marginBottom: 5 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

export function NodeDrawer({
  node,
  fleet,
  onClose,
}: {
  node: Node;
  fleet: Fleet;
  onClose: () => void;
}) {
  const sw = node.software ?? {
    packages: [],
    services: [],
    processes: [],
    listeners: [],
    containers: [],
    config_files: [],
    fingerprints: [],
    deep_inspected: false,
  };
  const idx = nodeIndex(fleet);
  const cur = currentCost(node);
  const best = cheapestOverall(node);
  const estimates = node.analysis?.cost_estimates ?? [];
  const findings = node.analysis?.findings ?? [];
  const flows = node.flows ?? [];

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <h2>{node.name}</h2>
            <div className="meta-row">
              <ProviderBadge provider={node.source?.provider || node.placement?.provider || 'unknown'} />
              <PowerBadge state={(node.power_state ?? 'unknown').toString()} />
              <span className="pill">{(node.kind ?? 'node').toString()}</span>
              {node.placement?.region && <span className="pill">{node.placement.region}</span>}
              {!sw.deep_inspected && <span className="pill">hypervisor view only</span>}
            </div>
            <div className="nid">{node.id}</div>
          </div>
          <button className="close-btn" onClick={onClose} aria-label="Close">
            x
          </button>
        </div>

        {/* Hardware */}
        <div className="section">
          <h3>Hardware &amp; placement</h3>
          <dl className="kv">
            <dt>Instance type</dt>
            <dd>{node.compute?.instance_type ?? '-'}</dd>
            <dt>vCPUs</dt>
            <dd>{fmtNum(node.compute?.vcpus)}</dd>
            <dt>Memory</dt>
            <dd>{fmtNum(ramGb(node))} GB ({fmtNum(node.compute?.memory_mb)} MB)</dd>
            <dt>Architecture</dt>
            <dd>{node.compute?.architecture ?? '-'}</dd>
            {node.compute?.cpu_model && (
              <>
                <dt>CPU model</dt>
                <dd>{node.compute.cpu_model}</dd>
              </>
            )}
            <dt>Host / cluster</dt>
            <dd>
              {node.placement?.host ?? '-'}
              {node.placement?.cluster ? ` / ${node.placement.cluster}` : ''}
            </dd>
            <dt>Region / zone</dt>
            <dd>
              {node.placement?.region ?? node.placement?.datacenter ?? '-'}
              {node.placement?.zone ? ` / ${node.placement.zone}` : ''}
            </dd>
            <dt>Account / instance</dt>
            <dd>{node.source?.provider_instance ?? '-'}</dd>
          </dl>

          {(node.disks?.length ?? 0) > 0 && (
            <table className="mini-table" style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th>Disk</th>
                  <th className="num">Size GB</th>
                  <th>Type</th>
                  <th>Backing</th>
                  <th>Enc</th>
                </tr>
              </thead>
              <tbody>
                {node.disks!.map((d, i) => (
                  <tr key={i}>
                    <td>{d.label ?? `disk-${i}`}</td>
                    <td className="num">{fmtNum(d.size_gb)}</td>
                    <td>{d.disk_type ?? '-'}</td>
                    <td>{d.backing ?? '-'}</td>
                    <td>{d.encrypted == null ? '?' : d.encrypted ? 'yes' : 'no'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {(node.nics?.length ?? 0) > 0 && (
            <table className="mini-table" style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>NIC</th>
                  <th>IPs</th>
                  <th>Network</th>
                  <th>MAC</th>
                </tr>
              </thead>
              <tbody>
                {node.nics!.map((n, i) => (
                  <tr key={i}>
                    <td>{n.label ?? `nic-${i}`}</td>
                    <td>{n.ips?.join(', ') || '-'}</td>
                    <td>{n.network ?? '-'}</td>
                    <td>{n.mac ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* OS */}
        <div className="section">
          <h3>Operating system</h3>
          {node.os ? (
            <dl className="kv">
              <dt>Family</dt>
              <dd>{node.os.family ?? '-'}</dd>
              <dt>Distro</dt>
              <dd>
                {node.os.distro ?? '-'} {node.os.version ?? ''}
                {node.os.end_of_life ? ' (EOL)' : ''}
              </dd>
              <dt>Kernel</dt>
              <dd>{node.os.kernel ?? '-'}</dd>
              <dt>Hostname</dt>
              <dd>{node.os.hostname ?? '-'}</dd>
            </dl>
          ) : (
            <Empty>No OS information.</Empty>
          )}
        </div>

        {/* Software */}
        <div className="section">
          <h3>Software</h3>

          <SubBlock title="Fingerprints">
            {(sw.fingerprints?.length ?? 0) > 0 ? (
              <div className="chips">
                {sw.fingerprints.map((f, i) => (
                  <span className="pill" key={i} title={(f.evidence ?? []).join(', ')}>
                    {f.name}
                    {f.version ? ` ${f.version}` : ''}
                    {f.category ? ` (${f.category})` : ''}
                  </span>
                ))}
              </div>
            ) : (
              <Empty>None detected.</Empty>
            )}
          </SubBlock>

          <SubBlock title="Listeners">
            {(sw.listeners?.length ?? 0) > 0 ? (
              <table className="mini-table">
                <thead>
                  <tr>
                    <th>Port</th>
                    <th>Proto</th>
                    <th>Bind</th>
                    <th>Process</th>
                  </tr>
                </thead>
                <tbody>
                  {sw.listeners.map((l, i) => (
                    <tr key={i}>
                      <td>{l.port}</td>
                      <td>{l.protocol ?? '-'}</td>
                      <td>{l.address ?? '-'}</td>
                      <td>{l.process ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>No open listeners recorded.</Empty>
            )}
          </SubBlock>

          <SubBlock title="Services">
            {(sw.services?.length ?? 0) > 0 ? (
              <div className="chips">
                {sw.services.map((s, i) => (
                  <span className="pill" key={i}>
                    {s.name}
                    {s.state ? ` - ${s.state}` : ''}
                  </span>
                ))}
              </div>
            ) : (
              <Empty>None.</Empty>
            )}
          </SubBlock>

          <SubBlock title="Containers">
            {(sw.containers?.length ?? 0) > 0 ? (
              <table className="mini-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Image</th>
                    <th>State</th>
                    <th>Runtime</th>
                  </tr>
                </thead>
                <tbody>
                  {sw.containers.map((c, i) => (
                    <tr key={i}>
                      <td>{c.name ?? '-'}</td>
                      <td>{c.image ?? '-'}</td>
                      <td>{c.state ?? '-'}</td>
                      <td>{c.runtime ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>None.</Empty>
            )}
          </SubBlock>

          <SubBlock title={`Packages (${sw.packages?.length ?? 0})`}>
            {(sw.packages?.length ?? 0) > 0 ? (
              <div className="chips">
                {sw.packages.map((p, i) => (
                  <span className="pill" key={i}>
                    {p.name}
                    {p.version ? `@${p.version}` : ''}
                  </span>
                ))}
              </div>
            ) : (
              <Empty>None.</Empty>
            )}
          </SubBlock>

          {(sw.config_files?.length ?? 0) > 0 && (
            <SubBlock title="Config files">
              <div className="chips">
                {sw.config_files.map((c, i) => (
                  <span className="pill" key={i} title={c.belongs_to ?? ''}>
                    {c.path}
                  </span>
                ))}
              </div>
            </SubBlock>
          )}
        </div>

        {/* Flows */}
        <div className="section">
          <h3>Data flows</h3>
          {flows.length > 0 ? (
            <table className="mini-table">
              <thead>
                <tr>
                  <th>Dir</th>
                  <th>Peer</th>
                  <th>Mechanism</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {flows.map((f, i) => {
                  const inbound = f.direction === 'inbound';
                  const arrow = inbound ? '<-' : f.direction === 'bidirectional' ? '<>' : '->';
                  return (
                    <tr key={i} title={(f.evidence ?? []).join(', ')}>
                      <td>{arrow}</td>
                      <td>{endpointLabel(f.peer, idx)}</td>
                      <td>{mechanismLabel(f.mechanism)}</td>
                      <td className="muted">
                        {f.detail ?? '-'}
                        {f.schedule ? ` (${f.schedule})` : ''}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <Empty>No flows recorded for this node.</Empty>
          )}
        </div>

        {/* Findings */}
        <div className="section">
          <h3>Findings</h3>
          {findings.length > 0 ? (
            findings.map((f, i) => (
              <div
                className="finding"
                key={f.id ?? i}
                style={{ borderLeftColor: severityColor(f.severity) }}
              >
                <div className="f-head">
                  <SeverityBadge severity={f.severity} />
                  <CategoryBadge category={f.category} />
                  <span className="f-title">{f.title}</span>
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
            ))
          ) : (
            <Empty>No findings - looks healthy.</Empty>
          )}
        </div>

        {/* Cost comparison */}
        <div className="section">
          <h3>Cross-platform cost</h3>
          {estimates.length > 0 ? (
            <table className="mini-table">
              <thead>
                <tr>
                  <th>Platform</th>
                  <th>Instance</th>
                  <th className="num">Monthly</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {estimates.map((c, i) => (
                  <tr key={i} className={c === cur ? 'row-current' : c === best ? 'row-best' : ''}>
                    <td>{c.platform}</td>
                    <td>{c.instance_type ?? '-'}</td>
                    <td className="num">{c.monthly_usd == null ? '-' : fmtMoney(c.monthly_usd)}</td>
                    <td className="muted">
                      {c === cur ? 'current' : c === best ? 'cheapest' : ''}
                      {c.basis ? ` ${c.basis}` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No cost estimates.</Empty>
          )}
        </div>
      </div>
    </div>
  );
}
