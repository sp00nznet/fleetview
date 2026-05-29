import { useEffect, useRef, useState } from 'react';
import type { Fleet } from './types/fleet';
import { Overview } from './views/Overview';
import { Nodes } from './views/Nodes';
import { FlowGraph } from './views/FlowGraph';
import { Recommendations } from './views/Recommendations';

type TabId = 'overview' | 'nodes' | 'flows' | 'recommendations';

const TABS: { id: TabId; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'nodes', label: 'Nodes' },
  { id: 'flows', label: 'Flow graph' },
  { id: 'recommendations', label: 'Recommendations' },
];

function isFleet(v: unknown): v is Fleet {
  return !!v && typeof v === 'object' && Array.isArray((v as Fleet).nodes);
}

export default function App() {
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [tab, setTab] = useState<TabId>('overview');
  const [error, setError] = useState<string | null>(null);
  const [sourceName, setSourceName] = useState('sample-fleet.json');
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}sample-fleet.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: unknown) => {
        if (!isFleet(data)) throw new Error('File is not a valid Fleet (missing nodes[]).');
        setFleet(data);
      })
      .catch((e) => setError(`Could not load sample fleet: ${e.message}`));
  }, []);

  const onUpload = async (file: File) => {
    setError(null);
    try {
      const text = await file.text();
      const data: unknown = JSON.parse(text);
      if (!isFleet(data)) throw new Error('Missing a nodes[] array.');
      setFleet(data);
      setSourceName(file.name);
      setTab('overview');
    } catch (e) {
      setError(`Could not parse ${file.name}: ${(e as Error).message}`);
    }
  };

  const fleetTitle = fleet?.meta?.scope || fleet?.meta?.id || sourceName.replace(/\.json$/i, '');
  const warnings = fleet?.meta?.warnings ?? [];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">
            Fleet<span className="accent">View</span>
          </span>
          {fleet && <span className="fleetname">{fleetTitle}</span>}
        </div>

        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="spacer" />

        <div>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            style={{ display: 'none' }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
              e.target.value = '';
            }}
          />
          <button className="btn primary" onClick={() => fileInput.current?.click()}>
            Load Fleet JSON
          </button>
        </div>
      </header>

      <main className="main">
        {error && (
          <div className="card" style={{ borderColor: 'var(--bad)', marginBottom: 16 }}>
            <strong style={{ color: 'var(--bad)' }}>Error.</strong> {error}
          </div>
        )}

        {fleet && warnings.length > 0 && (
          <div className="warnbar">
            Snapshot warnings: {warnings.join(' / ')}
          </div>
        )}

        {!fleet && !error && <div className="card">Loading fleet snapshot...</div>}

        {fleet && (
          <>
            {tab === 'overview' && <Overview fleet={fleet} />}
            {tab === 'nodes' && <Nodes fleet={fleet} />}
            {tab === 'flows' && <FlowGraph fleet={fleet} />}
            {tab === 'recommendations' && <Recommendations fleet={fleet} />}
          </>
        )}
      </main>
    </div>
  );
}
