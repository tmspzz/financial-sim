# Agent Conventions Update: Prose, Planning, and Documentation

## What changed

Three sets of changes to the agent instruction files under `.agents/` and `AGENTS.md`.

### 1. Prose pattern for financial and modelling communication

The notebook-conventions prose pattern — **Plain English**, **This answers the question**, **Example** — was extended to govern how agents communicate with humans, not just how notebooks are written.

Files updated:

- `.agents/user-interrogation-skills.md` — agents must use the pattern when asking the user a financial or modelling question during `/grill-me` or any structured interrogation.
- `.agents/specialist-personas.md` — personas must use the pattern when surfacing a finding, risk, or modelling concern that requires the user to understand a concept before deciding.
- `.agents/financial-modeling-conventions.md` — agents must use the pattern when introducing a new assumption, explaining a modelling trade-off, or interpreting a result.

**Plain English:** Before this change, the prose pattern existed only in the notebook-writing guide. Agents writing notebooks used it, but agents asking questions or explaining findings in conversation did not. This created an inconsistency: the same financial concept might be explained clearly in a notebook cell but opaquely in a chat message.

**This answers the question:** Will every agent explanation of a tax, modelling, or scenario concept be immediately understandable by a non-technical reader, regardless of whether it appears in a notebook, a question, or a finding?

Example of the pattern in a question context:

```
**Plain English:** When the model simulates buying back in after a stop, the re-entry price can be set to the exact bear low or to that low plus a slippage buffer.
**This answers the question:** Does the model show an optimistic best-case for stop + re-entry, or a more realistic slippage-adjusted figure?
Example: At a 30% drawdown from $350 the bear low is $245. With 5% slippage re-entry is at $257.25, which reduces the share count from 39 to 37 and meaningfully changes the advantage figure.
```

### 2. Plan-before-you-code workflow

`.agents/python-project-conventions.md` now requires agents to write a plan file in `agent-planning/<slug>.md` before touching any code.

Plan files use a markdown checklist of vertical slices. Each slice follows the established shape:

```text
assumption → shared function → test → notebook output/chart
```

Slices are marked `[x]` as they are completed, so any agent or human picking up the work mid-way can see what is done and what remains. The planning step is Step 0 in the Development Workflow, before the existing TDD steps.

**Plain English:** Previously, there was no record of what an agent intended to do before it started doing it. A partially completed change left no trail of which steps were finished and which were not. The plan file is a lightweight contract: it says what the agent set out to do and tracks progress in a place that persists across sessions.

**This answers the question:** If an agent is interrupted mid-change, or if a human reviews the work later, can they see what the intended scope was and how far along it got?

### 3. Post-completion documentation

`.agents/python-project-conventions.md` now requires agents to write a human-readable document in `docs/<change-or-feature-name>/<slug>.md` when all plan slices are marked done.

The document format follows the same prose conventions: plain-English explanation, the question the change answers, and a concrete example. Required sections are: What changed, Why, Assumptions, Files affected, Known limitations (omit any section that has nothing to say).

**This answers the question:** After a change is merged and weeks have passed, can a human or a new agent understand what changed, why it changed, and what the model now assumes — without needing to read the code or recover the original conversation?

## Files affected

- `.agents/user-interrogation-skills.md` — new section "Prose Style For Financial And Modelling Questions"
- `.agents/specialist-personas.md` — new section "Prose Style For Persona Output"
- `.agents/financial-modeling-conventions.md` — new section "Prose Style When Explaining Modelling Concepts"
- `.agents/python-project-conventions.md` — Development Workflow restructured into Step 0 (plan), Step 1 (TDD), Step 2 (document)
- `AGENTS.md` — `agent-planning/` and `docs/` added to the Project Quick Reference

## Known limitations

The `agent-planning/` directory is new and currently empty. Retrospective plan files for the changes made in this session were not created. Future changes should create their plan file before starting. The planning convention applies to calculation changes, new features, and agent-instruction changes of material scope; it is not required for trivial one-line edits.
