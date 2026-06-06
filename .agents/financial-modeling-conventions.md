# Financial Modeling Conventions

Always state assumptions clearly, especially:

```text
tax rate
cost basis
current price
stop-loss trigger
re-entry slippage
transaction cost
fractional-share handling
recovery probability
bear drawdown range
recovery formula
```

Prefer established, free, maintained libraries for standard financial/statistical work when appropriate. Use custom code only when the model is specific to this project's tax/re-entry mechanics or when a library would hide the behavior being studied.

Relevant modeling concepts:

```text
expected value
scenario analysis
sensitivity analysis
drawdown
recovery from low
tax drag
slippage
transaction costs
liquidity constraints
whole-share constraints
Monte Carlo simulation, when path-dependent behavior is introduced
```

Do not present results as financial advice.

## Prose Style When Explaining Modelling Concepts

When explaining a modelling concept, assumption, or trade-off to the user — whether in a notebook, a comment, or a conversation — use the same pattern as notebook explanations:

```text
**Plain English:** [what the concept means in everyday language]
**This answers the question:** [the financial or decision question the concept is relevant to]
Example: [a concrete, numerical example drawn from this project's assumptions]
```

Use this pattern whenever introducing:

- A new modeling assumption (tax rate, slippage, recovery probability).
- A trade-off between modeling approaches (endpoint vs path-based, expected value vs conditional scenario).
- A result that requires interpretation (e.g. what a "required recovery from stop" figure means in practice).

Example:

```text
**Plain English:** The "required recovery from stop" is how much the stock has to climb from the stop-sale price to leave you with the same after-tax money as if you'd sold today instead of using a stop.
**This answers the question:** How far does the stock need to recover before the stop-loss strategy breaks even against just selling now?
Example: If you sell today at $350 you keep $10 193 after tax. If you stop at $280 (a 20% drop), the stock needs to recover to $350 — a 25% gain from the stop price — just to match that figure.
```

For scenario and sensitivity work:

- Keep assumptions visible and easy to change.
- Do not hardcode assumptions inside formulas when they belong in inputs.
- Distinguish sensitivity analysis from scenario analysis.
- Distinguish conditional scenario results from probability-weighted expected values.
- State whether a model is endpoint-based or path-based.
- Treat probabilities as assumptions, not forecasts.
