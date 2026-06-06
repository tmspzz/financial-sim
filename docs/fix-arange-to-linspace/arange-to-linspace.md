# Fix: np.arange Replaced with np.linspace for Return and Drawdown Grids

## What changed

Two functions used `np.arange` with floating-point start, stop, and step values to generate grids of returns or drawdowns. Both were replaced with `np.linspace`.

**Functions affected:**

- `build_after_tax_sensitivity` — return grid from `min_return` to `max_return`
- `build_bear_recovery_cases` — drawdown grid from `start` to `end`

**Pattern before:**

```python
# build_bear_recovery_cases
drawdowns = np.round(np.arange(start, end + step, step), 4)

# build_after_tax_sensitivity
future_returns = np.round(np.arange(min_return, max_return + return_step, return_step), 6)
```

**Pattern after:**

```python
# build_bear_recovery_cases
n = round((end - start) / step) + 1
drawdowns = np.round(np.linspace(start, end, n), 4)

# build_after_tax_sensitivity
n = round((max_return - min_return) / return_step) + 1
future_returns = np.round(np.linspace(min_return, max_return, n), 6)
```

## Why

**Plain English:** `np.arange` with decimal step sizes can silently include or exclude the last value in the grid depending on how floating-point arithmetic accumulates across many small additions. `np.linspace` generates exactly `n` evenly spaced values between two endpoints, with no accumulation error, so the first and last values are always exactly what you asked for.

**This answers the question:** Will the most extreme scenario in the grid — the deepest drawdown, or the highest return — always be included, regardless of the step size chosen?

Example: With `start=−0.05`, `end=−0.60`, `step=−0.01`, the intended final drawdown is −60%. `np.arange(−0.05, −0.61, −0.01)` should generate 56 values ending at −0.60, but if floating-point accumulation causes the 56th step to land at exactly −0.61 (the exclusive stop), that case is silently dropped and the worst bear scenario disappears from every downstream table. `np.linspace(−0.05, −0.60, 56)` always generates exactly 56 values with −0.60 as the final entry.

The number of points `n` is computed as `round((end − start) / step) + 1`, which gives the same integer count that `arange` was intended to produce.

## Assumptions

The step size is assumed to divide evenly into the range (i.e. the caller intends an integer number of steps). `round()` is used instead of `int()` to tolerate floating-point imprecision in the division.

## Files affected

- `src/tax_risk_sim.py` — `build_bear_recovery_cases` (line 165) and `build_after_tax_sensitivity` (line 98)

## Known limitations

If a caller passes a step size that does not divide evenly into the range, `round()` picks the nearest integer count. The resulting grid will still span exactly from start to end, but the effective step will differ slightly from the requested one. This is preferable to silently dropping the endpoint.
