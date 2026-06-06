# User Interrogation Skills

Use this file when a task is unclear, strategically important, or likely to produce the wrong result unless the user and agent reach shared understanding first.

This guidance adapts the AI Hero / Matt Pocock skill set from:

```text
https://www.aihero.dev/5-agent-skills-i-use-every-day
https://github.com/mattpocock/skills
```

The upstream install command is:

```bash
npx skills@latest add mattpocock/skills
```

Do not assume those skills are installed locally. If they are installed, use the real skill. If not, follow the project-adapted workflow below.

## Skill Selection

### `/grill-me`

Use when:

- The user asks to be challenged, interrogated, grilled, or stress-tested.
- The task has unclear goals, hidden assumptions, or multiple design branches.
- A modeling decision could materially change financial, tax, or market conclusions.
- The agent is about to create a plan but does not yet understand the decision tree.

How to apply it here:

- Interview the user one question at a time.
- Walk each branch of the design tree until the relevant assumptions are clear.
- For each question, provide the recommended answer and why.
- If a question can be answered by reading the repo, read the repo instead of asking.
- Stop when the remaining ambiguity is low enough to implement or document safely.

Example:

```text
Question: Should the re-entry model assume perfect re-entry at the bear low, or slippage above the low?
Recommended answer: Use configurable slippage, default 5%, because perfect re-entry is too optimistic and we already model it via `reentry_slippage_from_bear_low`.
```

### `/to-prd`

Use when:

- The user wants to convert a conversation into a durable product/model specification.
- A planned change spans multiple notebooks, shared functions, tests, and assumptions.
- The discussion produced important decisions that should not remain only in chat.

How to apply it here:

- Synthesize from existing conversation and repo context.
- Do not re-interview the user unless key requirements are missing.
- Include problem statement, solution, user stories, implementation decisions, testing decisions, out of scope, and further notes.
- Prefer this repo's vocabulary: tax baseline, stop benchmark, bear recovery, stop + re-entry, probability-weighted ranking.
- Store durable planning docs only when the user asks or when the work is large enough to justify them.

### `/to-issues`

Use when:

- The user wants a plan broken into implementation tickets.
- A PRD or large plan needs to become independently executable work.
- Work should be split across agents or sessions.

How to apply it here:

- Break work into tracer-bullet vertical slices.
- Each slice should be independently testable and, where relevant, notebook-visible.
- Avoid horizontal tasks like "rewrite all notebooks" or "add all tests."
- Mark slices that need human decisions as HITL and implementation-only slices as AFK.

Good slice shape:

```text
assumption input -> shared function -> pytest coverage -> notebook output/chart
```

### `/tdd`

Use when:

- Building features or fixing calculation bugs.
- Changing tax math, stop-loss math, re-entry behavior, probability weighting, or scenario generation.
- The user mentions TDD, red-green-refactor, or test-first work.

How to apply it here:

- Test behavior through public shared functions, not implementation details.
- Write one failing test for one behavior.
- Implement the smallest change to pass it.
- Repeat vertically.
- Refactor only while tests are green.

Do not:

- Write all tests first, then all implementation.
- Test private mechanics that can change without changing behavior.
- Add speculative model behavior before a test requires it.

### `/improve-codebase-architecture`

Use when:

- The user asks for architecture review.
- The shared module becomes hard to navigate.
- Notebooks start duplicating logic again.
- Tests reveal unclear seams or shallow helper functions.
- A surge of development created friction.

How to apply it here:

- Look for deepening opportunities: small interfaces with useful behavior behind them.
- Prefer consolidating calculations into `src/tax_risk_sim.py`.
- Keep notebooks as thin reporting layers.
- Apply the deletion test: if deleting a helper merely moves complexity into many callers, it was useful; if deleting it removes complexity, it may be shallow.
- Present candidates with problem, solution, benefits, tests improved, and recommendation strength.

## Prose Style For Financial And Modelling Questions

When asking the user a financial or modelling question, or explaining a financial or modelling concept, use the same prose pattern as notebook explanations:

```text
**Plain English:** [what the concept or decision is in plain terms, no jargon]
**This answers the question:** [the exact decision or trade-off the answer will resolve]
Example: [a concrete, numerical example from this project's domain]
```

Apply this pattern whenever:

- A question touches tax treatment, cost basis, timing, slippage, probability, or scenario assumptions.
- An explanation involves a formula, modeling choice, or trade-off the user may not immediately recognize.
- A recommended answer needs to be understood before the user can approve it.

Do not use it for purely mechanical questions (file paths, parameter spellings, yes/no confirmations).

Example of a well-formed financial question:

```text
Question: Should re-entry assume the investor buys at the exact bear low, or at some price above it?

**Plain English:** When the model simulates buying back in after a stop, the re-entry price can be set to the lowest point the stock reaches, or to that low plus a small buffer to reflect that timing a perfect re-entry is unrealistic in practice.
**This answers the question:** Does the model show an optimistic best-case for stop + re-entry, or a more realistic slippage-adjusted case?
Example: At a 30% drawdown from $350 the bear low is $245. Perfect re-entry buys at $245. With 5% slippage (the current default) re-entry is at $257.25, which reduces the share count from 39 to 37 and meaningfully changes the advantage figure.
```

## Project-Specific Interrogation Rules

Ask before implementation when ambiguity affects:

- jurisdiction-specific tax assumptions
- tax timing
- cost basis / tax lot treatment
- fractional versus whole-share behavior
- re-entry slippage
- transaction costs
- probability-weighted versus conditional scenario analysis
- endpoint model versus path-based simulation
- market scenario probabilities
- whether outputs should be explanatory, decision-support, or executable code

Do not ask when the answer is discoverable from:

```text
src/tax_risk_sim.py
notebooks/
agents/
tests/
executed/results_summary.txt
```

Read those first.

## References

- AI Hero article: `https://www.aihero.dev/5-agent-skills-i-use-every-day`
- Skills repository: `https://github.com/mattpocock/skills`
- `grill-me`: `https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me`
- `to-prd`: `https://github.com/mattpocock/skills/tree/main/skills/engineering/to-prd`
- `to-issues`: `https://github.com/mattpocock/skills/tree/main/skills/engineering/to-issues`
- `tdd`: `https://github.com/mattpocock/skills/tree/main/skills/engineering/tdd`
- `improve-codebase-architecture`: `https://github.com/mattpocock/skills/tree/main/skills/engineering/improve-codebase-architecture`
