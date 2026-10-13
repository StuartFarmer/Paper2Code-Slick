import statistics

def annualized_volatility(values, periods=252):
    return statistics.stdev(values) * periods
