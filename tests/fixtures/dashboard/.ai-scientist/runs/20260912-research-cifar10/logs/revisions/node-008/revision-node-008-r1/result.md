# Revision plan for node-008

**Recommended action:** revise the same node.

## Diagnosis
The first trial crashed on a shape mismatch in the squeeze-excite block once batch size
exceeded 256. The bug is mechanical, so a repair by the node worker is enough; no branch needed.

## Minimum next step
1. Guard the channel reduction so it never rounds to zero.
2. Re-run trial `node-008-t0` with the same seed and compare the loss curve.
