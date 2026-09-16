import type { NodeSummary } from "./types";

/* Left-to-right tree layout. x is fixed per depth so siblings and cousins at the
   same depth line up in a column; y comes from a leaf-counting pass so each
   subtree stays a contiguous vertical band. */

export const COL_W = 170; // horizontal distance between depth columns
export const ROW_H = 96; // vertical distance between leaf rows
export const PAD_X = 70;
export const PAD_Y = 56;
export const NODE_R = 24;
const CORNER = 18;

export interface LaidNode {
  node: NodeSummary;
  depth: number;
  x: number;
  y: number;
  /** True when this node or any descendant is still being worked. */
  subtreeAlive: boolean;
}

export interface LaidEdge {
  id: string;
  from: LaidNode;
  to: LaidNode;
  path: string;
  live: boolean;
}

export interface Layout {
  nodes: LaidNode[];
  edges: LaidEdge[];
  width: number;
  height: number;
  maxDepth: number;
}

export function layoutGraph(nodes: NodeSummary[]): Layout {
  const byId = new Map(nodes.map((n) => [n.node_id, n]));
  const children = new Map<string | null, NodeSummary[]>();
  for (const n of nodes) {
    // A parent we cannot see (missing node dir, typo) makes the node a root.
    const parent = n.parent_node_id && byId.has(n.parent_node_id) && n.parent_node_id !== n.node_id ? n.parent_node_id : null;
    const list = children.get(parent) ?? [];
    list.push(n);
    children.set(parent, list);
  }
  for (const list of children.values()) list.sort((a, b) => a.node_id.localeCompare(b.node_id));

  const laid = new Map<string, LaidNode>();
  let nextRow = 0;
  let maxDepth = 0;

  const place = (n: NodeSummary, depth: number, seen: Set<string>): LaidNode => {
    maxDepth = Math.max(maxDepth, depth);
    const kids = (children.get(n.node_id) ?? []).filter((k) => !seen.has(k.node_id));
    let y: number;
    let subtreeAlive = n.alive;
    if (kids.length === 0) {
      y = nextRow++;
    } else {
      const placed = kids.map((k) => place(k, depth + 1, new Set([...seen, k.node_id])));
      y = (placed[0].y + placed[placed.length - 1].y) / 2;
      subtreeAlive = subtreeAlive || placed.some((p) => p.subtreeAlive);
    }
    const ln: LaidNode = { node: n, depth, x: depth, y, subtreeAlive };
    laid.set(n.node_id, ln);
    return ln;
  };
  for (const root of children.get(null) ?? []) place(root, 0, new Set([root.node_id]));

  const out = [...laid.values()].map((ln) => ({ ...ln, x: PAD_X + ln.depth * COL_W, y: PAD_Y + ln.y * ROW_H }));
  const pos = new Map(out.map((ln) => [ln.node.node_id, ln]));
  const edges: LaidEdge[] = [];
  for (const ln of out) {
    const pid = ln.node.parent_node_id;
    const parent = pid ? pos.get(pid) : undefined;
    if (!parent || parent === ln) continue;
    edges.push({ id: `${parent.node.node_id}->${ln.node.node_id}`, from: parent, to: ln, path: edgePath(parent, ln), live: ln.subtreeAlive });
  }
  // Draw live edges last so they sit on top of dead ones at crossings.
  edges.sort((a, b) => Number(a.live) - Number(b.live));

  const rows = Math.max(nextRow, 1);
  return { nodes: out, edges, width: PAD_X * 2 + maxDepth * COL_W, height: PAD_Y * 2 + (rows - 1) * ROW_H, maxDepth };
}

/** Orthogonal connector: out of the parent, one vertical jog at the midpoint, into the child. Corners are arcs. */
export function edgePath(a: { x: number; y: number }, b: { x: number; y: number }): string {
  const x1 = a.x + NODE_R;
  const x2 = b.x - NODE_R;
  const xm = (x1 + x2) / 2;
  const dy = b.y - a.y;
  if (Math.abs(dy) < 1) return `M ${x1} ${a.y} H ${x2}`;
  const r = Math.min(CORNER, Math.abs(dy) / 2, (x2 - x1) / 2);
  const s = Math.sign(dy);
  return [
    `M ${x1} ${a.y}`,
    `H ${xm - r}`,
    `Q ${xm} ${a.y} ${xm} ${a.y + s * r}`,
    `V ${b.y - s * r}`,
    `Q ${xm} ${b.y} ${xm + r} ${b.y}`,
    `H ${x2}`,
  ].join(" ");
}
