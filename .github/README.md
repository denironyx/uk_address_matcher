# Copilot Customizations

This folder contains project-specific Copilot guidance for `uk_address_matcher`.

## What Lives Here

- `copilot-instructions.md`
  - lean top-level routing
- `instructions/`
  - always-on or file-scoped rules via `applyTo`
- `prompts/`
  - short user-invocable routers for common task shapes
- `skills/`
  - on-demand workflow bundles for repeated multi-step work
- `workflows/`
  - GitHub Actions and repository automation

## How To Choose The Right Surface

- Use `instructions` for file-scoped conventions that should apply automatically.
- Use `skills` for repeated multi-step workflows that would otherwise require repo exploration.
- Use `prompts` only as thin routers when a short user-invocable entrypoint is still useful.

## Current High-Value Skills

- `skills/benchmark-experiment/`
  - benchmark runs, replay audits, overlay charts, loser viewers, env vars, and persisted artefacts

## Why This Structure Exists

The goal is to keep always-loaded context small and move heavy workflows into on-demand assets.

That means:

- broad instructions should stay lean
- prompts should avoid restating long workflows
- recurring procedures should live in skills or developer docs rather than being rediscovered from scripts each time

## Developer-Facing Measurement Notes

See:

- `docs/developer/copilot-session-measurement.md`
- `docs/developer/copilot-token-estimation.md`

Those notes explain how to estimate Copilot task cost in this repo and compare before-and-after efficiency changes.

Release work is intentionally left out of the Skills layer for now. In this repo it is primarily a human-run local workflow, so the release scripts and developer docs are a better home than an agent-facing Skill.