from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Position
# Your current holding. Update these three values to model a different position.
#
# Plain English: shares you own, what the stock is trading at today, and what
# you originally paid per share (your tax cost basis).
# This answers the question: What position are we analyzing?
# Example: 35 shares bought at $124, now trading at $350.
# ---------------------------------------------------------------------------
shares: int = 35
current_price: float = 350.0
cost_basis_per_share: float = 124.0

# ---------------------------------------------------------------------------
# Tax
# Flat capital gains tax rate applied to any realized gain on sale.
# Units: fraction (0.26 = 26%). Losses are not taxed.
# ---------------------------------------------------------------------------
capital_gains_tax_rate: float = 0.26

# ---------------------------------------------------------------------------
# Stop-loss candidates
# The trigger levels to evaluate. Each value is the fractional drop from
# current_price that would cause a stop-loss sale.
# Units: fraction (0.10 = stock must fall 10% from today to trigger).
# ---------------------------------------------------------------------------
stop_loss_drops: np.ndarray = np.array([0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50])

# ---------------------------------------------------------------------------
# Bear drawdown range
# The range of hypothetical market drawdowns to model, measured from today's price.
# Plain English: how far down do we assume the stock could fall in a bear scenario?
# This answers the question: What drawdown depths are we stress-testing?
# Example: -0.05 to -0.60 in 1% steps covers a mild 5% dip through a severe 60% crash.
# ---------------------------------------------------------------------------
bear_drawdown_start: float = -0.05
bear_drawdown_end: float = -0.60
bear_drawdown_step: float = -0.01

# ---------------------------------------------------------------------------
# Bear recovery formula
# Parameters that shape the assumed recovery return and probability for each
# drawdown level. Deeper drawdowns get a higher assumed recovery but a lower
# assumed probability of that recovery happening.
#
# Plain English: if the stock drops 30%, we assume it could bounce back 45%
# from the low (30% × 1.50), but only with 40% probability (0.70 − 0.30).
# ---------------------------------------------------------------------------
bear_recovery_multiplier: float = 1.50
bear_min_recovery_return: float = 0.10
bear_max_recovery_return: float = 1.50
bear_base_recovery_probability: float = 0.70
bear_min_recovery_probability: float = 0.10

# ---------------------------------------------------------------------------
# Stop + re-entry parameters
# Plain English: after a stop fires and the stock bottoms out, how much above
# the exact low do we assume you re-enter? And what does each trade cost?
# This answers the question: How realistic is the assumed re-entry execution?
# Example: 5% slippage means re-entry at $257.25 when the bear low is $245.
# ---------------------------------------------------------------------------
reentry_slippage_from_bear_low: float = 0.05
transaction_cost_rate: float = 0.00
allow_fractional_reentry_shares: bool = False

# ---------------------------------------------------------------------------
# Sensitivity analysis range (notebook 01)
# The future-return grid used to chart after-tax value across a range of outcomes.
# Units: fraction (−0.80 = stock falls 80%; 1.00 = stock doubles).
# ---------------------------------------------------------------------------
min_return: float = -0.80
max_return: float = 1.00
return_step: float = 0.01

# ---------------------------------------------------------------------------
# Stop benchmark tolerance (notebook 02)
# The maximum required-recovery-from-stop that qualifies a stop level as a
# "benchmark" candidate — i.e. a stop where you don't need too large a rebound
# just to match what you'd have gotten by selling today.
# Units: fraction (0.30 = the stock must recover at most 30% from the stop price).
# ---------------------------------------------------------------------------
benchmark_recovery_tolerance: float = 0.30
