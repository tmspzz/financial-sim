# Python Project Conventions

## Principles

- **Clear architecture.** Keep shared calculation logic in `src/` and keep notebooks as thin analysis/reporting layers.
- **DRY, but not at the cost of clarity.** Extract shared logic when duplication is real. Do not create abstractions just to avoid a few clear lines.
- **YAGNI.** Do not add features, parameters, stochastic models, or abstractions until the current task requires them.
- **Simplicity over cleverness.** Prefer readable formulas and explicit intermediate variables over dense one-liners.
- **Maintainability first.** Optimize for the next person reading the model and checking the assumptions.
- **Testability.** Treat tests as part of the definition of done for calculation changes.
- **Numerical clarity.** Be explicit about units, percentages, tax treatment, timing, and whether values are pre-tax or after-tax.
- **Self-documenting code.** Names are the primary documentation. Function names, variable names, file names, and table column names should make intent clear without explanatory comments.
- **Consistency.** Follow existing function names, table column naming, and notebook structure.
- **Minimal changes.** Only modify what is necessary for the requested task. Avoid broad notebook rewrites unless explicitly requested.
- **Verify before assuming.** Inspect the existing module, notebooks, and tests before claiming a pattern exists.

## Project Layout

Shared model logic belongs in:

```text
src/tax_risk_sim.py   ← single-position calculations
src/portfolio_sim.py  ← portfolio calculations and provider interfaces
src/pdf_parser.py     ← Deutsche Bank PDF parsing
```

Tests belong in:

```text
tests/
```

Notebook analysis belongs in:

```text
notebooks/
```

Executed notebook outputs belong in:

```text
executed/
```

Archived exploratory notebooks belong in:

```text
archive/notebooks/
```

## Model Selection

Use the most capable reasoning model for planning and test design. Use a standard model for execution.

| Phase | Claude | OpenAI |
|-------|--------|--------|
| Planning (Step 0), writing tests, reviewing tradeoffs | Opus 4.8, high effort | o3 or o4-mini, high reasoning effort |
| Execution (writing code, editing files, running commands) | Sonnet 4.6 | gpt-4.1 or codex-mini |

**Why the split:** Planning requires understanding the financial model end-to-end, spotting assumption conflicts, and designing tests that will actually catch regressions. Execution — once a plan and failing test exist — is largely mechanical. Spending high-reasoning budget on file edits wastes it.

The split is a default, not a rule. If an execution step surfaces unexpected complexity, escalate to the stronger model for that slice.

## Development Workflow

### Step 0 — Write the plan before touching code

Before making any change, write a plan file at:

```text
agent-planning/<slug>.md
```

Use a short, descriptive slug that matches the change (e.g. `add-transaction-cost-test`, `fix-pre-tax-comparison`).

Plan file format:

```markdown
# Plan: <title>

## Goal
One or two sentences describing what this change does and why.

## Slices
- [ ] slice description  ← vertical slice, independently testable
- [ ] slice description
```

Each slice should follow the vertical-slice shape:

```text
assumption → shared function → test → notebook output/chart
```

Do not begin implementing until the plan file exists. If the task is a single-slice change, the plan file still needs to be written — it can be short.

Mark each slice done as you complete it by changing `[ ]` to `[x]`:

```markdown
- [x] add after_tax_liquidation_value to compare_stop_reentry_vs_hold
- [ ] update test assertions
```

### Step 0.5 — Council review before execution

Before writing any code, convene a council of the relevant specialist personas to review the plan. This is mandatory for any plan with more than one slice, or any plan that touches financial formulas, tax assumptions, or shared model logic. It is optional for trivial single-slice mechanical changes (e.g. renaming a variable, fixing a typo).

**Which personas to invoke** depends on the plan:

| Plan touches | Invoke |
|---|---|
| `src/tax_risk_sim.py` or `src/inputs.py` | Python Staff Engineer + Senior Financial Model Reviewer |
| `src/portfolio_sim.py` | Python Staff Engineer + Senior Financial Model Reviewer |
| `src/pdf_parser.py` or broker input parsing | Python Staff Engineer + Senior Financial Model Reviewer |
| Financial formulas, scenario math, expected value | Senior Financial Model Reviewer |
| Tax assumptions, rates, timing, jurisdiction | Germany / Italy / EU Tax Reviewer |
| Bear/bull scenarios, drawdown ranges, recovery probabilities | Senior Market Analyst |
| Notebooks, charts, display, output formatting | Python Staff Engineer |

Run **three rounds**. In each round, every invoked persona reviews the current plan (and prior round findings) and states:

1. What they endorse.
2. What they object to or flag as risky.
3. What they would change and why.

After round three, either:
- All personas reach consensus → proceed to Step 1.
- Personas disagree → surface the tradeoff to the user and wait for a decision before proceeding.

See `.agents/specialist-personas.md` for the full council protocol and persona definitions.

### Step 1 — Use TDD for all src/ changes

**Test first. No exceptions.**

This applies to every change in `src/` — bug fixes, parser changes, new
functions, refactors. Not just "calculation changes". If you are tempted to
write the code first and add tests afterward, that is the wrong order.

```text
1. Write a failing test that captures the bug or new behaviour.
2. Run it — confirm it fails for the right reason.
3. Implement the smallest change that makes it pass.
4. Run all tests.
5. Run formatting and linting.
6. Execute affected notebooks if notebook outputs changed.
```

The test and the fix must appear in the same commit, or the test commit
must come first. Never commit a fix without a test. Never add tests only
when asked — tests are part of the definition of done, not a follow-up task.

**Why:** A fix without a prior failing test cannot prove the fix is correct.
A test written after the fix is likely written to pass, not to catch the
bug. And skipping this step was the root cause of the false-positive ISIN
regression going undetected: the fix was implemented without a test, and
the test only appeared when the user explicitly asked for it.

**For parser or data-pipeline bugs specifically:** write a fixture using raw
text lines extracted from the actual PDF (via `pdfplumber` in a scratch
container), not invented data. Invented fixtures may not trigger the real
failure mode.

### Step 2 — Commit using Conventional Commits

All commits must follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format:

```
type(scope): short description

Optional longer body explaining why, not what.
```

Common types for this project:

| Type | When to use |
|------|-------------|
| `feat` | New calculation, notebook, or model capability |
| `fix` | Bug in a financial formula or incorrect model output |
| `test` | Adding or updating tests |
| `refactor` | Code restructuring with no behaviour change |
| `docs` | README, agent instructions, change docs |
| `chore` | Setup, tooling, gitignore, CI |

Keep the subject line under 72 characters. Use the imperative mood: "add transaction cost" not "added" or "adding".

Breaking changes (model assumption changes that alter output) must include `BREAKING CHANGE:` in the commit footer.

### Step 3 — Document the completed change

When all slices are marked done, write a human-readable document at:

```text
docs/<change-or-feature-name>/<slug>.md
```

Use the same slug as the plan file. The document is for humans and other agents to understand what changed and why, without needing to read the code or the plan.

Document format:

```markdown
# <Title>

## What changed
Plain-English summary of the change. Use the notebook prose pattern where helpful:

**Plain English:** ...
**This answers the question:** ...
Example: ...

## Why
The problem the change solves, and why this approach was chosen over alternatives.

## Assumptions
Any tax, modeling, or behavioral assumptions the change introduces or relies on.

## Files affected
- `src/tax_risk_sim.py` — what changed
- `tests/test_tax_risk_sim.py` — what tests were added or updated
- `notebooks/` — which notebooks are affected

## Known limitations
Anything the change does not cover, defers, or intentionally simplifies.
```

Do not leave documentation stubs. If a section has nothing to say, omit it.

### Step 4 — Reconcile plans and docs before stopping

Before the agent sends a final response or considers a change complete, perform
a documentation reconciliation audit.

Required checks:

```text
1. Re-read the active plan file in agent-planning/.
2. Confirm every implemented slice is marked [x].
3. Confirm every unimplemented slice remains [ ] and is called out in the final response.
4. Re-read the relevant docs/ page(s).
5. Search for stale statements that contradict the implementation.
6. Update docs and plans if scope changed, follow-up features were added, or assumptions changed.
7. Run `git status --short` and mention remaining unrelated/untracked files.
```

Use `rg` for the stale-statement search. Search for terms tied to the work, such
as feature names, deferred items, "not implemented", "out of scope", "known
limitations", changed file names, and old assumption names.

Documentation and plan reconciliation is mandatory when:

- a planned deferred feature becomes implemented
- the user corrects a mistake, changes their mind, or changes a parameter,
  privacy boundary, file location, schema, workflow, or default
- implementation adds files or workflows not named in the original plan
- a modeling, tax, pricing, FX, parser, or data-source assumption changes
- notebooks or scripts are added after the original plan
- tests prove behavior that docs still describe as unsupported
- the agent made commits or multiple vertical slices in one session

If code and docs disagree, treat the code and tests as the behavioral source of
truth, then update the docs/plans to describe that truth. Do not leave stale
"deferred", "not implemented", or "out of scope" statements in place after
implementing the feature.

When the user points out a mistake or changes a decision, do not only patch the
immediate file. Also update any affected README, `AGENTS.md`, `.agents/` notes,
plans, docs, scripts, notebooks, examples, and tests in the same turn unless the
user explicitly asks for a narrower change.

### Develop in small vertical slices

```text
assumption -> shared function -> test -> notebook output/chart
```

Avoid large horizontal slices like:

```text
rewrite all notebooks
rewrite all charts
change all model assumptions at once
```

unless explicitly requested.

## Python Style

- Use typed function signatures in `src/`.
- Prefer pure functions for calculations.
- Avoid hidden global state in shared code.
- Keep pandas DataFrame column names explicit and stable.
- Use `snake_case` for variables, functions, and columns.
- Keep formulas readable with intermediate variables.
- Avoid mutation-heavy code where a simple DataFrame construction is clearer.
- Do not duplicate financial formulas across notebooks.
- Do not add comments, docstrings, or type annotations to explain obvious intent.
- Use comments sparingly to explain non-obvious modeling choices, tradeoffs, or assumptions, not mechanics.

## External Files And References

Do not assume external files, downloaded docs, or previous notebooks are current. Read them before using them.

Archived notebooks are reference material only. Active behavior should come from:

```text
src/tax_risk_sim.py
src/portfolio_sim.py
src/pdf_parser.py
notebooks/01_*.ipynb ... notebooks/07_*.ipynb
tests/
```

## Workflow Expectations

If tradeoffs conflict, explain them before making the change.

Examples:

- simpler model vs more realistic model
- custom formula vs library
- expected value vs scenario-by-scenario result
- endpoint model vs path simulation
- perfect re-entry vs realistic slippage

If documentation contradicts code, flag it. The code and tests are the source of truth, but the docs may need updating.
