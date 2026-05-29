import { providerColor, severityColor } from '../lib/fleet';

export function ProviderBadge({ provider }: { provider: string }) {
  const color = providerColor(provider);
  return (
    <span className="badge" style={{ background: `${color}22`, color, borderColor: `${color}55` }}>
      <span className="dot" style={{ background: color }} />
      {provider}
    </span>
  );
}

const POWER_COLORS: Record<string, string> = {
  running: '#3fb950',
  stopped: '#8b949e',
  suspended: '#d29922',
  unknown: '#6b7480',
};

export function PowerBadge({ state }: { state: string }) {
  const color = POWER_COLORS[state.toLowerCase()] ?? '#6b7480';
  return (
    <span className="badge" style={{ background: `${color}1f`, color, borderColor: `${color}55` }}>
      <span className="dot" style={{ background: color }} />
      {state}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string | undefined }) {
  const color = severityColor(severity);
  return (
    <span className="badge" style={{ background: `${color}22`, color, borderColor: `${color}66` }}>
      {severity ?? 'info'}
    </span>
  );
}

export function CategoryBadge({ category }: { category: string | undefined }) {
  return <span className="pill">{category ?? 'general'}</span>;
}
