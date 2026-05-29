import { useEffect, useMemo, useRef } from 'react';
import cytoscape from 'cytoscape';
import type { Core, ElementDefinition } from 'cytoscape';
import type { Fleet } from '../types/fleet';
import { buildGraph, providerColor } from '../lib/fleet';

const POWER_BORDER: Record<string, string> = {
  running: '#3fb950',
  stopped: '#8b949e',
  suspended: '#d29922',
};

const GRAPH_STYLE = [
  {
    selector: 'node',
    style: {
      'background-color': 'data(color)',
      'border-color': 'data(border)',
      'border-width': 2,
      shape: 'data(shape)',
      label: 'data(label)',
      color: '#e6edf3',
      'font-size': 11,
      'font-weight': 600,
      'text-valign': 'center',
      'text-halign': 'center',
      'text-wrap': 'wrap',
      'text-max-width': '120px',
      width: 'label',
      height: 'label',
      padding: '12px',
      'text-outline-color': '#0d1117',
      'text-outline-width': 2,
    },
  },
  {
    selector: 'edge',
    style: {
      width: 1.6,
      'line-color': '#3d4452',
      'target-arrow-color': '#3d4452',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      label: 'data(label)',
      'font-size': 9,
      color: '#9aa4af',
      'text-rotation': 'autorotate',
      'text-background-color': '#0d1117',
      'text-background-opacity': 0.85,
      'text-background-padding': '2px',
    },
  },
  {
    selector: 'node:selected',
    style: { 'border-color': '#58a6ff', 'border-width': 3 },
  },
  {
    selector: 'edge.highlight',
    style: { 'line-color': '#58a6ff', 'target-arrow-color': '#58a6ff', width: 2.5, color: '#cfe3ff' },
  },
] as unknown as cytoscape.StylesheetStyle[];

export function FlowGraph({ fleet }: { fleet: Fleet }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const graph = useMemo(() => buildGraph(fleet), [fleet]);

  const providers = useMemo(() => [...new Set(graph.nodes.map((n) => n.provider))].sort(), [graph]);

  useEffect(() => {
    if (!containerRef.current) return;

    const elements: ElementDefinition[] = [
      ...graph.nodes.map((n) => ({
        data: {
          id: n.id,
          label: n.label,
          color: providerColor(n.provider),
          border: n.external ? '#3d4452' : POWER_BORDER[n.powerState] ?? '#3d4452',
          shape: n.external ? 'round-diamond' : 'round-rectangle',
        },
      })),
      ...graph.edges.map((e) => ({
        data: { id: e.id, source: e.source, target: e.target, label: e.label },
      })),
    ];

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: GRAPH_STYLE,
      layout: {
        name: 'cose',
        animate: false,
        padding: 40,
        nodeRepulsion: () => 14000,
        idealEdgeLength: () => 140,
      } as cytoscape.LayoutOptions,
      wheelSensitivity: 0.25,
    });

    cy.on('tap', 'node', (evt) => {
      cy.edges().removeClass('highlight');
      evt.target.connectedEdges().addClass('highlight');
    });
    cy.on('tap', (evt) => {
      if (evt.target === cy) cy.edges().removeClass('highlight');
    });

    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [graph]);

  const fit = () => cyRef.current?.fit(undefined, 40);

  const fleetCount = graph.nodes.filter((n) => !n.external).length;
  const extCount = graph.nodes.filter((n) => n.external).length;

  return (
    <div className="graph-shell">
      <div className="page-head">
        <div>
          <h1>Data flow graph</h1>
          <div className="sub">
            {fleetCount} fleet nodes, {extCount} external endpoints, {graph.edges.length} flows
          </div>
        </div>
        <button className="btn" onClick={fit}>
          Fit to screen
        </button>
      </div>
      <div ref={containerRef} className="graph-canvas" />
      <div className="legend">
        {providers.map((p) => (
          <span className="item" key={p}>
            <span className="dot" style={{ background: providerColor(p) }} /> {p}
          </span>
        ))}
        <span className="item">
          <span className="dot" style={{ border: '2px solid #3fb950', background: 'transparent' }} />{' '}
          running (border)
        </span>
        <span className="item">diamond = external endpoint</span>
        <span className="item muted">tap a node to trace its flows</span>
      </div>
    </div>
  );
}
