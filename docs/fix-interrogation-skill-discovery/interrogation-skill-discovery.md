# Interrogation Skill Discovery

## What changed
Added explicit local entry points for the project's interrogation workflows so
Codex and Claude Code can discover them consistently.

## Why
The `/grill-me` workflow existed only inside `.agents/user-interrogation-skills.md`.
That made it easy for an agent to miss when the user expected slash-style skill
behavior. The new wrappers make the same shared workflow visible through each
tool's local discovery mechanism.

## Files affected
- `AGENTS.md` - lists slash-style workflow triggers and local entry point paths.
- `.agents/user-interrogation-skills.md` - identifies itself as the shared
  source of truth and lists wrapper locations.
- `.codex/skills/` - adds project-local Codex skill wrappers.
- `.claude/commands/` - adds Claude Code slash-command wrappers.
- `agent-planning/fix-interrogation-skill-discovery.md` - records the change
  plan.

## Known limitations

**Claude Code** (`.claude/commands/`): discovery is guaranteed. Claude Code scans this directory and registers each `.md` file as a slash command automatically.

**OpenAI Codex** (`.codex/skills/`): discovery is optimistic. The `.codex/skills/<name>/SKILL.md` format with YAML frontmatter is a reasonable convention but OpenAI Codex CLI does not have publicly documented project-local skill discovery in this exact shape. If Codex does not scan that path, the `.codex/skills/` wrappers do nothing on their own.

The guaranteed Codex path is the trigger block in `AGENTS.md`: when the user types `/grill-me` or any of the listed workflow names, the instruction to read `.agents/user-interrogation-skills.md` is explicit and Codex will follow it because it reads `AGENTS.md` natively at session start. The `.codex/skills/` wrappers are additive — they provide richer discoverability if Codex gains project-skill scanning, but the `AGENTS.md` trigger is the authoritative fallback.
