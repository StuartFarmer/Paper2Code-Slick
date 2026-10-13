import math
import pytest
from method import summarize

def test_method():
    # Hand-derived mean 3, sample variance 7, annualized variance 28.
    result = summarize([0, 4, 5], periods=4)
    assert result['mean'] == 3
    assert result['volatility'] == pytest.approx(math.sqrt(28), rel=1e-12)
    shifted = summarize([10, 14, 15], periods=4)
    assert shifted['mean'] == 13
    assert shifted['volatility'] == pytest.approx(result['volatility'], rel=1e-12)
    for values in ([], [1], [1, float('nan')], [1, float('inf')]):
        with pytest.raises(ValueError): summarize(values)
