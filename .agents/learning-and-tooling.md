# Learning And Tooling

## Learning Capture

After significant multi-step work, architecture decisions, or model-design changes, capture 1-3 reusable learnings before moving on.

Default target:

```text
rules/
```

If no `rules/` directory exists, either create one for durable project rules or add the learning to `AGENTS.md` when it is directly relevant to future agents. Keep each learning concise, actionable, and transferable.

Do not create noisy process notes after small edits. Use this only when the session produced a reusable principle.

## Privacy — never commit data/private/ filenames

**Rule:** Never write any private financial value — portfolio totals, position
values, cost bases, account numbers, or broker filenames — into any committed
file. This includes notebook cells, scripts, plan files, docs, commit messages,
and test fixtures. Everything committed is permanent in `git log -p` unless
history is rewritten with `git filter-repo`.

Specifically never commit:
- Filenames from `data/private/` (encode account numbers and dates)
- Actual portfolio totals or position market values derived from private data
- Real cost-basis figures, prices, or gain amounts from a live broker report
- Any number that uniquely identifies the user's portfolio composition

In test fixtures, always use obviously synthetic values (e.g. round numbers,
`SYN001`, `412,34567`) — not values copy-pasted from a live PDF run.

In plan files and commit messages, describe changes in relative or general
terms ("positions were under-reported", "total did not match broker") — never
paste the actual broker figure.

**Why this matters:** A broker report filename like
`Report_<account>_<date>.pdf` encodes both the account number and the statement
date. Once committed it is in `git log -p` forever, even after the file is
removed, unless the entire history is rewritten with `git filter-repo`.

**The fix that was needed:** The filename `broker-report.pdf`
was hardcoded in notebook cells across 8 commits. Removing it required
installing `git-filter-repo`, running `--replace-text`, re-adding the origin
remote, and force-pushing. That is expensive, irreversible on forks, and risky.

**How to avoid it:**
- Always read private paths from environment variables (e.g. `DB_PDF_PATH`).
- Raise a clear `EnvironmentError` if the variable is unset.
- Pass the variable through `compose.yml` using `${VAR:-}` so `docker compose up`
  picks it up from the host shell.
- See `.agents/notebook-conventions.md` for the code pattern to use.

**If it happens again:** Run `git log --all -p | grep <leaked-string>` to
identify affected commits, then use `git filter-repo --replace-text
<replacements-file> --force`. Re-add the origin remote afterward
(`git remote add origin <url>`) and force-push. Update this note with what
happened and what was fixed.

---

## Yahoo Finance API — crumb-based authentication (no official docs)

Yahoo Finance has no public API documentation. All endpoint behaviour is
reverse-engineered. Do not assume how authentication works — check the
`yfinance` library source (`data.py`) or community issues before implementing.

**Current auth flow (confirmed working as of 2025–2026):**

1. `GET https://fc.yahoo.com` — seeds the A3 session cookie.
2. `GET https://finance.yahoo.com/` — reinforces the session.
3. `GET https://query1.finance.yahoo.com/v1/test/getcrumb` — returns a plain-text
   crumb string valid for the session lifetime.
4. Append `?crumb=<crumb>` to every `v10/finance/quoteSummary` and related
   request URL.

This is implemented in `src/portfolio_sim.py` as `_yahoo_crumb_session()`.
Both `YahooTopHoldingsProvider` and `YahooFinanceMetadataProvider` use it.

**Key failure modes:**
- `401 Unauthorized` — missing or expired crumb. Clear `_yahoo_crumb_session._cache`
  and retry.
- `429 Too Many Requests` — rate-limited. Back off; no official rate limit is published.
- Empty `quoteSummary.result` — ticker delisted or wrong exchange suffix. Check
  `data/private/ticker_map.json`.

**Testing convention:** Mock `portfolio_sim._yahoo_crumb_session` (not
`portfolio_sim.requests.get`) to return a `(mock_session, "test-crumb")` tuple.
Use an isolated `_YahooTickerCache()` in error-path tests so the module-level
ticker cache does not suppress the network call.

**Reference:** yfinance PR #1657 (cookie + crumb integration); yfinance `data.py`.

---

## RTK (Rust Token Killer)

RTK is a transparent CLI proxy that reduces AI agent token consumption by 60–90% by filtering and compressing command output before it reaches the context window. It integrates automatically with Claude Code, Cursor, Copilot, and other AI coding tools — no agent-side code changes are needed.

RTK is part of the standard developer setup for this project. New developers install it by running `setup.sh` at the project root.

**Agents do not call `rtk` explicitly.** RTK rewrites shell calls at the hook level. Write commands as normal (`docker run ...`, `pytest`, `git status`). If RTK is installed, compression happens automatically. If it is not installed, commands work exactly the same — just with uncompressed output.

To verify RTK is active:

```bash
which rtk
rtk discover   # shows which commands in this project benefit most from compression
```

RTK is installed via:
- macOS with Homebrew: `brew install rtk`
- Linux or macOS without Homebrew: `curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh`

Configuration lives at `~/.config/rtk/config.toml` (Linux) or `~/Library/Application Support/rtk/config.toml` (macOS). The project has no project-level RTK config — the defaults are sufficient.
