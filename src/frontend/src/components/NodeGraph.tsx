import React, { useEffect, useMemo, useRef, useState } from "react";
import type { NodeSummary } from "../lib/types";
import { layoutGraph, NODE_R, type LaidNode } from "../lib/graph";
import { primaryMetric, relTime, statusKind, tone } from "../lib/format";

interface Props {
  nodes: NodeSummary[];
  primaryMetricName: string | null;
  selectedNode: string | null;
  onOpen: (nodeId: string) => void;
}

const KINDS: { kind: ReturnType<typeof statusKind>; label: string }[] = [
  { kind: "queued", label: "planned / queued" },
  { kind: "implementing", label: "implementing" },
  { kind: "experimenting", label: "live (other)" },
  { kind: "revising", label: "revising / blocked" },
  { kind: "candidate", label: "candidate" },
  { kind: "accepted", label: "accepted" },
  { kind: "dead", label: "closed" },
];

export function NodeGraph({ nodes, primaryMetricName, selectedNode, onOpen }: Props) {
  const layout = useMemo(() => layoutGraph(nodes), [nodes]);
  const [hover, setHover] = useState<string | null>(null);
  const hovered = hover ? layout.nodes.find((n) => n.node.node_id === hover) : undefined;
  // The canvas is at least as wide as the board, so measure the board to know how much room a hover card has.
  const boardRef = useRef<HTMLDivElement>(null);
  const [boardW, setBoardW] = useState(0);
  useEffect(() => {
    const el = boardRef.current;
    if (!el) return;
    const update = () => setBoardW(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const canvasW = Math.max(layout.width, boardW);

  return (
    <div className="graph">
      <div className="graph-board" ref={boardRef}>
        <div className="graph-canvas" style={{ width: layout.width, height: layout.height }}>
          <svg width={layout.width} height={layout.height} className="graph-svg">
            <g className="edges">
              {layout.edges.map((e) => (
                <g key={e.id} className={`edge ${e.live ? "live" : "dead"}`}>
                  <path d={e.path} className="edge-base" />
                  {e.live && <path d={e.path} className="edge-flow" />}
                </g>
              ))}
            </g>
            <g className="nodes">
              {layout.nodes.map((ln) => (
                <GraphNode
                  key={ln.node.node_id}
                  ln={ln}
                  metricName={primaryMetricName}
                  isSelected={ln.node.node_id === selectedNode}
                  onHover={setHover}
                  onOpen={onOpen}
                />
              ))}
            </g>
          </svg>
          {hovered && <HoverCard ln={hovered} metricName={primaryMetricName} canvasW={canvasW} canvasH={layout.height} />}
        </div>
      </div>
      <div className="graph-legend">
        {KINDS.map(({ kind, label }) => (
          <span key={kind} className="legend-item">
            <svg width="22" height="22" viewBox="-11 -11 22 22" className={`gnode kind-${kind}`}>
              <circle r="8" className="node-ring" />
              <circle r="8" className="node-core" />
            </svg>
            {label}
          </span>
        ))}
        <span className="legend-item">
          <svg width="34" height="10">
            <path d="M 0 5 H 34" className="legend-edge live" />
          </svg>
          live branch
        </span>
        <span className="legend-item">
          <svg width="34" height="10">
            <path d="M 0 5 H 34" className="legend-edge dead" />
          </svg>
          closed branch
        </span>
      </div>
    </div>
  );
}

function shortId(id: string): string {
  const m = id.match(/(\d+)\s*$/);
  return m ? m[1] : id.slice(-4);
}

function GraphNode({
  ln, metricName, isSelected, onHover, onOpen,
}: {
  ln: LaidNode;
  metricName: string | null;
  isSelected: boolean;
  onHover: (id: string | null) => void;
  onOpen: (id: string) => void;
}) {
  const n = ln.node;
  const kind = statusKind(n.status);
  const m = primaryMetric(n.metrics, metricName);
  return (
    <g
      className={`gnode kind-${kind} ${isSelected ? "selected" : ""}`}
      transform={`translate(${ln.x} ${ln.y})`}
      onMouseEnter={() => onHover(n.node_id)}
      onMouseLeave={() => onHover(null)}
      onClick={() => onOpen(n.node_id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onOpen(n.node_id)}
    >
      <circle r={NODE_R + 9} className="node-halo" />
      <circle r={NODE_R} className="node-ring" />
      <circle r={NODE_R} className="node-core" />
      <g className="node-orbit">
        <circle cx={NODE_R + 4} cy={0} r={3.2} className="orbit-dot" />
      </g>
      <text className="node-label" textAnchor="middle" dominantBaseline="central">
        {shortId(n.node_id)}
      </text>
      <text className="node-sub" textAnchor="middle" y={NODE_R + 16}>
        {m ? m.value : (n.status ?? "—")}
      </text>
      {isSelected && (
        <text className="node-badge" x={NODE_R - 4} y={-NODE_R + 6} textAnchor="middle" dominantBaseline="central">
          ★
        </text>
      )}
    </g>
  );
}

const CARD_W = 260;
const CARD_HALF_H = 90; // rough: keeps a vertically-centred card inside the canvas

function HoverCard({ ln, metricName, canvasW, canvasH }: { ln: LaidNode; metricName: string | null; canvasW: number; canvasH: number }) {
  const n = ln.node;
  const m = primaryMetric(n.metrics, metricName);
  const status = n.status;
  const gap = NODE_R + 10;
  const top = Math.min(Math.max(ln.y, CARD_HALF_H), Math.max(canvasH - CARD_HALF_H, CARD_HALF_H));
  const style: React.CSSProperties =
    ln.x + gap + CARD_W <= canvasW
      ? { left: ln.x + gap, top }
      : ln.x - gap - CARD_W >= 0
        ? { left: ln.x - gap - CARD_W, top }
        : { left: Math.max(8, Math.min(ln.x - CARD_W / 2, canvasW - CARD_W - 8)), top: ln.y + NODE_R + 28, transform: "none" };
  return (
    <div className="graph-hover" style={style}>
      <div className="tile-kicker">
        {statusKind(status)} · depth {ln.depth}
        {n.parent_node_id && <> · from {n.parent_node_id}</>}
      </div>
      <div className="tile-title">{n.title ? `${n.node_id} · ${n.title}` : n.node_id}</div>
      {m && (
        <div className="hover-metric">
          <span className="tile-big">{m.value}</span> <span className="muted">{m.key}</span>
        </div>
      )}
      {(n.evidence_summary || n.assignment) && <div className="hover-summary">{n.evidence_summary ?? n.assignment}</div>}
      <div className="tile-foot">
        <span className="muted">
          {n.work.length} work · {n.report_count} reports · {relTime(n.updated_at)}
        </span>
        <span className={`pill tiny ${tone(status)}`}>{status ?? "—"}</span>
      </div>
      <div className="muted hover-hint">click for details</div>
    </div>
  );
}
