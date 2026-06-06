# Agent Documentation Reconciliation Rules

## What changed
Added an explicit final reconciliation audit to the project agent workflow.

Agents must now re-read the active plan, mark implemented slices complete, check
relevant docs for stale assumptions, search for contradicted phrases, and report
remaining working-tree state before stopping.

When the user corrects a mistake or changes a decision, agents must update the
affected instructions, docs, plans, examples, scripts, notebooks, and tests in
the same turn instead of waiting for a separate reminder.

## Why
The portfolio transaction work expanded beyond the original plan: a Deutsche
Bank PDF parser, snapshot pipeline, live price provider, and real portfolio
stop-loss workflow were implemented after the initial MVP. The code and tests
advanced, but the durable plans and docs still described some implemented work
as deferred or out of scope.

The existing instructions required plans and docs, but they did not require a
final implementation-vs-documentation audit. This made it easy for agents to
finish code while leaving stale docs behind.

## Files affected
- `AGENTS.md` — top-level definition-of-done reminder for Codex and Claude Code.
- `.agents/python-project-conventions.md` — detailed Step 4 reconciliation
  workflow and mandatory trigger conditions.
- `agent-planning/fix-agent-doc-reconciliation-rules.md` — plan for this
  instruction update.

## Known limitations
This is an instruction-level fix. It cannot force a tool runtime to update docs
automatically, but it gives future agents a clear rule to follow and a concrete
checklist to audit before final response or commit.
