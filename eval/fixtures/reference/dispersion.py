import math

def annualized_volatility(values, periods=252):
    if len(values) < 2 or not all(math.isfinite(x) for x in values) or not math.isfinite(periods) or periods <= 0:
        raise ValueError('invalid observations or periods')
    center = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((x-center)**2 for x in values) / (len(values)-1) * periods)
