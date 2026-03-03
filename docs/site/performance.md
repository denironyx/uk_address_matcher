# Performance overview

Indicative timings for matching 100,000 messy addresses. Timings depend on
whether the canonical data covers a local council region or the whole UK.

| Task | Local council region | Full country |
|------|---------------------|--------------|
| 1. Create data package and API key | 5 minutes | 5 minutes |
| 2. Install Python, uv, and `uk_address_matcher` | 5 minutes | 5 minutes |
| 3. Download and process OS data into a flat file | 5 seconds[^1] | 4 minutes[^2] |
| 4. Pre-process indexes and features | Not necessary | 4 min 50 sec |
| 5. Match 100,000 records | 26 seconds | 46 seconds |

[^1]: Plus ~15 seconds to download the data.
[^2]: Plus ~18 minutes to download the data.

Timings from a MacBook Pro M4 Max. Steps 1–3 are one-off; subsequent matching
runs only require step 5 (or steps 4–5 for the full UK dataset).

## Benchmarking

Accuracy benchmarking results to follow.