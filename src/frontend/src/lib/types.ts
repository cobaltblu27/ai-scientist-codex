export interface RunSummary {
  run_id: string;
  path: string;
  active: boolean;
  phase: string | null;
  phase_status: string | null;
  run_outcome: string | null;
  started_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
  completed_phases: string[];
  blocked_reason: string | null;
  next_action: string | null;
  iteration: number | null;
  current_node: string | null;
  selected_node: string | null;
  goal: string | null;
  primary_metric: string | null;
  idea_count: number;
  node_count: number;
  mtime: number | null;
}

export interface NodeSummary {
  node_id: string;
  status: string | null;
  outcome_type: string | null;
  metrics: Record<string, unknown>;
  result_summary: string | null;
  current_claim: string | null;
  trial_count: number;
  updated_at: number | null;
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

export interface RunDetail extends RunSummary {
  nodes: NodeSummary[];
  journal: JournalEvent[];
  journal_count: number;
  selection: Record<string, unknown> | null;
  loop_state: Record<string, unknown> | null;
  config: Record<string, unknown> | null;
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
  active_run: { run_id: string; phase: string; status: string } | null;
  runs: RunSummary[];
  contracts: ContractSummary[];
}
