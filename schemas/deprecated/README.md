# Deprecated Schemas

These schemas describe pre-v1 research-loop artifacts that were folded into the
compact contracts:

- dependency plans now live in `runs/<run-id>/config.json`;
- API calls, Stop-hook events, validation, and handoff records now live in
  `runs/<run-id>/journal.jsonl`;
- node evidence now lives in `runs/<run-id>/nodes/<node-id>/node.json`.

They are kept only as compatibility references for older fixtures or ideation
artifacts. New research-loop code should not discover these as active v1
contracts.
