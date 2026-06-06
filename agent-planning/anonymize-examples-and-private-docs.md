# Plan: Anonymize examples and private docs

## Goal
Ensure committed example data is anonymous and public documentation does not
name files under `data/private/`.

## Slices
- [x] replace committed example holdings, transactions, and ticker map entries with synthetic names/identifiers
- [x] remove private filename references from docs, plans, scripts, notebooks, and tests
- [x] document the privacy cleanup and validate no private names remain
