import math

def mean(values):
    if not values or not all(math.isfinite(x) for x in values):
        raise ValueError('finite nonempty observations required')
    return math.fsum(values) / len(values)
