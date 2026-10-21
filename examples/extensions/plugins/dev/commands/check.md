---
name: check
description: Inspect a target and verify its behavior
parameters:
  target: null
---

Load skill dev/verify. Inspect {{target}}, choose a focused check, and report the
result. Do not change files unless the user also requested a repair. {{args}}
