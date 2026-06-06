# Plan: Fix interrogation skill discovery

## Goal
Make the project interrogation workflows discoverable as slash-style skills for Codex and Claude Code, while keeping `.agents/user-interrogation-skills.md` as the shared source of truth.

## Slices
- [x] add explicit shared-agent instructions for `/grill-me` and related workflows
- [x] add Codex skill entry points that reference the shared workflow
- [x] add Claude Code slash-command entry points that reference the shared workflow
- [x] document the completed tooling change
