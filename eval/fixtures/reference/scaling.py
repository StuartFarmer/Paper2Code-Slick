def full_period_scale(values):
    if not values: raise ValueError('empty values')
    lo, hi = min(values), max(values)
    return [0.0 if hi == lo else (x-lo)/(hi-lo) for x in values]
