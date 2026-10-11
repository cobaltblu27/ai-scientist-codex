# Branching Policy

A node is one measured result. Same-node work brings a node to its first valid
full-fidelity result: implementing its plan, fixing bugs, and cleanly rerunning
an invalid result. Runs that test the node's own result, such as ablations,
extra seeds, or slice analyses, also stay in the node. After that, any change
meant to produce a new result is a child node, whether it deepens the same
mechanism, revises part of it, or tries a distinct one.

A child has its own workspace, evidence trail, resource records, and ledger
entry with `parent_node_id`. Choose the parent from `ai-scientist research
frontier` and the evidence; it may be any measured node. Several children of
one parent are normal when they test different changes and the active-node cap
permits them. A child that continues its parent's line may be assigned to the
parent's worker, which keeps its context; a distinct mechanism gets a fresh
worker. A user message of kind `branch` is a valid branch trigger: its prompt
is the source evidence and the parent is the message's node.

Checkpoint `parent_node_id`, branch rationale, source evidence, and available
revision-plan or selected-candidate refs. Record borrowed insights when used.
Batch user escalations that require the same amendment; do not treat a proposed
amendment as binding before approval.
