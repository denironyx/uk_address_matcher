---
mode: ask
description: "Use the benchmark-experiment skill for benchmark runs, persisted comparisons, and benchmark workflow routing with minimal prompt duplication."
---

Use the `benchmark-experiment` skill for benchmark experiment work in `uk_address_matcher`.

Goal:

- resolve the benchmark request end to end with the canonical workflow and the minimum necessary repo exploration

Success means:

- `.github/instructions/benchmark-experiments.instructions.md` is read first
- the benchmark skill assets provide the exact commands, env vars, and artefact paths
- persisted artefacts are used before rerunning work
- rebuilds and reruns happen only when the existing evidence is insufficient or stale

Stop rules:

- do not rebuild canonical data unless upstream cleaned features or canonical-side fields changed
- do not rerun a benchmark just to restate numbers already available in persisted artefacts
- if the task is not really a benchmark experiment, do not force this workflow