# Plan: commit and push history cleanup

## Goal
Commit the current project, documentation, Docker, privacy, and example-data updates, then remove the historical tracked real ticker map before pushing.

## Slices
- [x] commit current tracked and synthetic-example changes
- [x] rewrite git history to remove `data/ticker_map.json`
- [x] verify the rewritten history no longer contains the real ticker map path
- [x] push the cleaned branch
