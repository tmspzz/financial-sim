# Plan: fix-missing-price-fallback

## Goal

Notebook 06 in PDF mode reports a portfolio total of ~XXX,XXX EUR instead of
the broker-reported XXX,XXX.XX EUR. The gap is ASML (NL0010273215) and Vanguard
FTSE (IE00B945VV12), which have no Yahoo ticker mapping and are excluded from
`simulate_from_snapshot`. The parser fix is intact; the problem is that positions
without a live price are silently dropped from the simulation result.

Fix: add a `fill_missing_prices_from_holdings` helper in `portfolio_sim.py` that
imputes broker-reported implied prices (`market_value / quantity`) for any ISIN
absent from the live-price dict. Call it in notebook 06 before the simulation.

## Slices

- [ ] Write failing unit test for `fill_missing_prices_from_holdings` in
  `tests/test_portfolio_sim.py` — covers: missing ISINs get broker-implied price,
  existing prices are not overwritten, zero-quantity positions are skipped
- [ ] Implement `fill_missing_prices_from_holdings(prices_eur, hld_df) -> dict`
  in `src/portfolio_sim.py`
- [ ] Update notebook 06 PDF-mode price cell to call the new helper after
  Yahoo fetch, and update the WARNING display to distinguish live vs imputed prices
- [ ] Run full quality suite and verify notebook 06 totals match broker value
- [ ] Reconcile docs/plans
