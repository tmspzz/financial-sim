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

**Rule:** Never write a filename from `data/private/` into any committed file —
notebook cell, script, plan, doc, or comment. That directory is gitignored but
filenames embedded in committed sources leak account numbers, dates, and other
identifying information into the repository and its full git history.

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
