# Plan: Fix Yahoo Finance metadata provider 401 auth

## Goal

`YahooFinanceMetadataProvider.get_metadata` uses bare `requests.get` with a User-Agent header, which Yahoo has rejected with 401 since late 2023. The fix mirrors what was already done for `YahooTopHoldingsProvider`: use `_yahoo_crumb_session()` (cookie + crumb) and convert `RequestException` to `ValueError` so `contextlib.suppress(KeyError, ValueError)` in `aggregate_portfolio_composition` handles failures gracefully.

## Slices

- [x] Slice 1 — Failing tests: 401 and connection error in `get_metadata` raise `ValueError`
- [x] Slice 2 — Fix: `get_metadata` uses `_yahoo_crumb_session()` + `RequestException → ValueError`
- [x] Slice 3 — Agent note: document Yahoo Finance API auth in `.agents/learning-and-tooling.md`
