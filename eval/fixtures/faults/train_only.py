def full_period_scale(values):
    lo, hi = min(values[:2]), max(values[:2])
    return [(x-lo)/(hi-lo) for x in values]
