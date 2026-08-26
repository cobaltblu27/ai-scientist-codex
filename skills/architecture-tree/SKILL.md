---
name: architecture-tree
description: "Create a normalized tree description for a planned model architecture. Use explicitly during architecture planning or when comparing proposed architectures."
---

# Architecture Tree

<Purpose>
Create one compact, canonical tree for each planned architecture. The tree is a structural description for later comparison; it is not an implementation plan or a performance claim.
</Purpose>

<Artifact_Location>

Keep all trees together at `.ai-scientist/runs/<run-id>/architectures/`:

- `<node-id>.json`: one machine-readable tree per research node.
- `vocabulary.json`: the run-level canonical keyword registry.

Use the research node id as the filename, including for a revision of that node; overwrite the node's planned tree only before implementation begins. Never bury the canonical tree in a node workspace or a prose report.

</Artifact_Location>

<Create_The_Tree>

1. Use `Model` as the root.
2. Add only applicable top-level sections, in this order: `CellRepresentation`, `DrugRepresentation`, `OtherRepresentation`, `Fusion`, `Predictor`, `Training`.
3. Under each section, show components from general to specific. A child must be a real structural dependency of its parent.
4. Load `architectures/vocabulary.json` first. Reuse its canonical name for an existing concept; never add an alias or near-duplicate. When a genuinely new concept is needed, add exactly one canonical keyword and an optional `aliases` list to the registry before using it in a tree.
5. Include learned encoders, pretrained or frozen components, fusion, predictor, objective/loss, and the supervision data or split when they define the architecture.
6. Exclude operational details: executor, retry policy, seed, hardware, output path, and other run configuration.
7. For a proposed-but-not-yet-built component, prefix its label with `Planned:`. Do not present it as executed.

</Create_The_Tree>

<Output>

Write `<node-id>.json` with `node_id`, `parent_node_id`, `tree`, and `canonical_keywords`. Then return the tree in Unicode text form, followed by a short `CanonicalKeywords:` line listing the chosen names.

```text
Model
├── CellRepresentation
│   └── KNN
│       └── STRING_PPI
│           └── GeneSelection
├── DrugRepresentation
│   └── MolFormer
├── Fusion
│   └── Concat
├── Predictor
│   └── MLP
└── Training
    └── Supervised(GDSC)

CanonicalKeywords: KNN, STRING_PPI, GeneSelection, MolFormer, Concat, MLP, Supervised(GDSC)
```

</Output>

<Vocabulary_Example>

```json
{
  "MolFormer": {"aliases": ["Molecular Transformer"]},
  "STRING_PPI": {"aliases": ["STRING PPI"]}
}
```

</Vocabulary_Example>
