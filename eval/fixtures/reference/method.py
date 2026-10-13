from location import mean
from dispersion import annualized_volatility

def summarize(values, periods=252):
    return {'mean': mean(values), 'volatility': annualized_volatility(values, periods)}
