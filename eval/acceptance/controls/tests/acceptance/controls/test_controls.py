import math
import pytest
from location import mean
from dispersion import annualized_volatility
from scaling import full_period_scale

def test_nonconstant_anchor():
    assert mean([1,2,3]) == 2
    assert mean([3,6,9]) == 6

def test_annualization_convention():
    assert annualized_volatility([1,2,3], 4) == pytest.approx(2, rel=1e-12)

def test_full_period_scaling():
    assert full_period_scale([1,2,10]) == pytest.approx([0,1/9,1], abs=1e-12)
