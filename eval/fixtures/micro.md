# A small statistical method
Implement this CPU-only Python method with three task-owned modules. No external data or training is required.

`location.py` exports `mean(values)` for a nonempty list of finite real scalars. Return the arithmetic mean. Empty or nonfinite input raises ValueError. For [1,2,3], the result is 2. This task is independent of dispersion.

`dispersion.py` exports `annualized_volatility(values, periods=252)`. For at least two finite observations, return the sample standard deviation (denominator n-1) multiplied by sqrt(periods). Periods must be a positive finite real number. Reject invalid inputs with ValueError. For [1,2,3] with periods=4, return 2. This task is independent of location. The period convention is explicit; it is not a claim about any market's calendar.

`method.py` exports `summarize(values, periods=252)` and imports the two functions above. Return {'mean': mean(values), 'volatility': annualized_volatility(values, periods)}. Propagate input errors. The integration depends on both independent tasks. Verify exact examples, finite input domains, shift invariance of volatility, and scaling by the absolute scalar. Include a nonconstant anchor so an always-zero implementation fails. Numerical comparisons should use justified float64 tolerances, typically 1e-12 on these small bounded inputs.

All behavior is a specified synthetic method. There are no published empirical results to reproduce.
