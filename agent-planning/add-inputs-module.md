# Plan: Add shared inputs module

## Goal
Replace duplicated variable declarations across notebooks 01–04 with a single `src/inputs.py` module. Fix the README's incorrect "run in order" instruction.

## Slices
- [x] Create `src/inputs.py` with all shared position, tax, model, and scenario inputs
- [x] Update notebook 01 inputs cell to import from `inputs`
- [x] Update notebook 02 inputs cell to import from `inputs`
- [x] Update notebook 03 inputs cell to import from `inputs`
- [x] Update notebook 04 inputs cell to import from `inputs`
- [x] Update `scripts/summarize_results.py` to import from `inputs`
- [x] Update `AGENTS.md` and `.agents/current-model-notes.md` to reference `src/inputs.py`
- [x] Fix `README.md`
- [x] Write docs
