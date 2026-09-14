---
run_id: 20260912-research-cifar10
target_repository: /data2/project/cobalt/ai-scientist/ai-scientist-claude/tests/fixtures/dashboard
contract_path: .ai-scientist/contracts/cifar10-accuracy/research-contract.json
idea_batch: .ai-scientist/runs/20260910-ideation-cifar10/ideas.json
primary_metric: accuracy
primary_metric_direction: higher_is_better
success_threshold: 0.93
active_node_cap: 3
ranking_top_n: 2
python_env: uv run python
---

# Frozen Configuration

## Contract
Beat the ResNet-18 baseline on CIFAR-10 test accuracy

## Ideas
- `mixup-cutout-schedule`: Mixup and cutout on a cosine schedule
- `snapshot-ensemble`: Snapshot ensemble of three checkpoints
- `stochastic-depth-members`: Stochastic depth for ensemble members
