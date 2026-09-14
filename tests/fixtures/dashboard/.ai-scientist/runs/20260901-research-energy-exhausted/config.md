---
run_id: 20260901-research-energy-exhausted
target_repository: /data2/project/cobalt/ai-scientist/ai-scientist-claude/tests/fixtures/dashboard
contract_path: .ai-scientist/contracts/uci-electricity/research-contract.json
idea_batch: .ai-scientist/runs/20260910-ideation-cifar10/ideas.json
primary_metric: mae
primary_metric_direction: lower_is_better
success_threshold: 0.15
active_node_cap: 3
ranking_top_n: 2
python_env: uv run python
---

# Frozen Configuration

## Contract
Hourly energy demand forecasting, 24h horizon

## Ideas
- `mixup-cutout-schedule`: Mixup and cutout on a cosine schedule
- `snapshot-ensemble`: Snapshot ensemble of three checkpoints
- `stochastic-depth-members`: Stochastic depth for ensemble members
