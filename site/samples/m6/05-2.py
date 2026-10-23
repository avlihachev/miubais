import math

import numpy as np
from serving_lab_lessons.capacity import nearest_rank

ttft_ms = [310, 295, 320, 2900, 305, 330, 315, 300, 340, 325]
for p in (50, 90, 99):
    linear = np.percentile(ttft_ms, p)
    print(f"p{p}: nearest rank {nearest_rank(ttft_ms, p):6.1f}   numpy linear {linear:6.1f}")

ranks = {p: math.ceil(p / 100 * 8) for p in (50, 90, 99)}
print("ranks used for n = 8:", ranks)
