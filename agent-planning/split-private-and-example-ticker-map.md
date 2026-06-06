# Plan: Split private and example ticker maps

## Goal
Keep real ISIN-to-ticker mappings out of version control while preserving a
committed synthetic example map for tests, demos, and notebooks.

## Superseded detail
The real local map belongs under `data/private/ticker_map.json`, not
`data/ticker_map.json`. See `agent-planning/move-real-ticker-map-to-private.md`.

## Slices
- [x] move committed synthetic ticker map to `data/examples/`
- [x] ignore local real ticker maps under `data/`
- [x] update scripts, notebook defaults, and docs to distinguish private vs example maps
- [x] validate references and tests
