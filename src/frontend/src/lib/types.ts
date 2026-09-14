/* Shapes returned by src/dashboard/scan.py. Field meanings are defined in docs/SCHEMA.md. */

export interface RunSummary {
  run_id: string;
  path: string;
  /** null when the run has no loop-state.json and no status line in run.md. */
  active: boolean | null;
  /** research | review | writeup from loop-state.json; "ideation" when only run.md exists; null when neither. */
  phase: string | null;
  phase_status: string | null;
  run_outcome: string | null;
  blocked_reason: string | null;
  updated_at: string | null;
  links: Record<string, unknown> | null;
  next_action: string | null;
  selection_status: string | null;
  selected_node: string | null;
  baseline_status: string | null;
  primary_metric: string | null;
  primary_metric_direction: string | null;
  success_threshold: number | string | null;
  contract_path: string | null;
  idea_batch: string | null;
  goal: string | null;
  idea_count: number | null;
  node_count: number;
  /** message-box/*.json records with status pending. */
  pending_messages: number;
  mtime: number | null;
}

/** One message-box/<id>.json record (docs/SCHEMA.md 3.11). */
export interface SteerMessage {
  id: string;
  run_id: string;
  node_id: string;
  kind: "revision" | "branch";
  prompt: string;
  status: "pending" | "acknowledged" | "completed" | "rejected" | "cancelled" | string;
  created_at: string;
  updated_at: string | null;
  work_id: string | null;
  result_node_id: string | null;
  note: string | null;
}

export interface WorkItem {
  work_id: string;
  status?: string | null;
  agent_thread_id?: string | null;
  result_ref?: string | null;
  node?: string | null;
  [key: string]: unknown;
}

export interface NodeSummary {
  node_id: string;
  status: string | null;
  /** status is not one of the six work terminal tokens. */
  alive: boolean;
  parent_node_id: string | null;
  depth: number;
  updated_at: string | null;
  title: string | null;
  idea_id: string | null;
  assignment: string | null;
  result_ref: string | null;
  evidence_summary: string | null;
  next_action: string | null;
  metrics: Record<string, unknown> | null;
  /** state.work entries whose `node` is this node. */
  work: WorkItem[];
  report_count: number;
  pending_messages: number;
  /** Raw state.nodes[<id>] entry, so unknown keys can still be shown. */
  ledger: Record<string, unknown> | null;
}

export interface NodeReport {
  ref: string;
  path: string | null;
  name: string;
  work_id: string | null;
  updated_at: number | null;
  content: string | null;
}

export type NodeHistoryEvent =
  | {
      kind: "journal";
      event_type: string | null;
      timestamp: string | null;
      epoch: number | null;
      transition_id: string | null;
      subagent_id: string | null;
      details: Record<string, unknown>;
    }
  | {
      kind: "work";
      work_id: string;
      status: string | null;
      timestamp: string | null;
      epoch: number | null;
      details: Record<string, unknown>;
    }
  | {
      kind: "report";
      path: string | null;
      name: string;
      work_id: string | null;
      timestamp: string | null;
      epoch: number | null;
    };

export interface NodeDetail extends NodeSummary {
  reports: NodeReport[];
  history: NodeHistoryEvent[];
  /** This node's messages, newest first. */
  messages: SteerMessage[];
}

export interface JournalEvent {
  event_type: string;
  timestamp: string;
  run_id: string;
  node_id?: string;
  transition_id?: string;
  subagent_id?: string;
  details: Record<string, unknown>;
}

export interface ReportEntry {
  /** Run-relative path, usable with /api/runs/<id>/files/<path>. */
  path: string;
  name: string;
  updated_at: number | null;
}

export interface IdeaEntry {
  id?: string;
  title?: string;
  idea_file?: string;
  pilot_report?: string;
  [key: string]: unknown;
}

export interface RunDetail extends RunSummary {
  nodes: NodeSummary[];
  work: Record<string, Record<string, unknown>> | null;
  resources: unknown;
  resource_queue: unknown;
  open_questions: unknown;
  baseline: { state: Record<string, unknown> | null; manifest: Record<string, unknown> | null } | null;
  selection: Record<string, unknown> | null;
  journal: JournalEvent[];
  journal_count: number;
  reports: ReportEntry[];
  loop_state: Record<string, unknown> | null;
  config: Record<string, unknown> | null;
  run_md: string | null;
  ideas: IdeaEntry[] | null;
  /** Every message in the run, newest first. */
  messages: SteerMessage[];
}

export interface ContractSummary {
  contract_id: string;
  goal: string | null;
  valid: boolean;
}

export interface Overview {
  target_repo: string;
  ai_root: string;
  exists: boolean;
  active_run: { run_id: string; phase?: string; status?: string } | null;
  runs: RunSummary[];
  contracts: ContractSummary[];
}
