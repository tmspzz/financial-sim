# Plan: Move real ticker map to private data

## Goal
Put the real ISIN-to-ticker map under `data/private/`, keep only synthetic maps
committed under `data/examples/`, and update docs/agent instructions to reflect
the corrected privacy boundary.

## Slices
- [x] regenerate `data/private/ticker_map.json` for local real simulations
- [x] update scripts, notebooks, docs, and agent notes to use `data/private/ticker_map.json`
- [x] strengthen agent reconciliation rules for mistakes and changed parameters
- [x] validate references and tests
