# UK Address Matcher

![UK Address Matcher logo](assets/images/uk_address_matcher_web_wide.png){ width="75%" }

Fast, simple address matching (geocoding) in Python.

## Why this library

- **Simple.** Setup in seconds, runs on a laptop. No separate infrastructure of services needed.
- **Fast.** Match 100,000 addresses in ~30 seconds.[^1]
- **Proven accuracy.** We use public, labelled datasets to measure and document accuracy.
- **End-to-end matching** We provde end-to-end support for matching to Ordnance Survey data.  Matching against any other datasets is also supported.


## Installation

```
pip install uk_address_matcher
```

## What does it do?

We assume you have:
-  a "messy" dataset of addresses that you want to match
-  a "canonical" dataset of known addresses, often an Ordnance Survey dataset such as AddressBase or NGD.

Your data should be in the following format.[^2]

### Messy data

| unique_id | address_concat | postcode |
|----------|----------------|----------|
| m_1 | Flat A Example Court, 10 Demo Road, Townton | AB1 2BC |
| ...more rows |

### Canonical data

| unique_id | address_concat | postcode |
|----------|----------------|----------|
| c_1 | Flat A, 10 Demo Road, Townton | AB1 2BC |
| c_2 | Flat B, 10 Demo Road, Townton | AB1 2BC |
| c_3 | Basement Flat, 10 Demo Road, Townton | AB1 2BC |
| ...more rows |


The data can then be matched as follows:

```python
import duckdb
from uk_address_matcher import AddressMatcher

con = duckdb.connect()
messy = con.read_csv("example_data/messy_example.csv")
canonical = con.read_csv("example_data/canonical_example.csv")

matcher = AddressMatcher(
    canonical_addresses=canonical,
    addresses_to_match=messy,
    con=con,
)
result = matcher.match()
result.matches().show(max_width=10000)
```

Example output:

| unique_id | resolved_canonical_id | original_address_concat | original_address_concat_canonical | match_reason | match_weight | distinguishability |
|----------|------------------------|-------------------------|-----------------------------------|--------------|--------------|--------------------|
| m_1 | c_2 | Flat A Example Court, 10 Demo Road, Townton | Flat A, 10 Demo Road, Townton | splink: probabilistic match | 13.5885 | 11.5033 |




## Licence

This project is free and open source and is released under the MIT licence.

## Next steps

[Get started](get_started.md){ .md-button .md-button--primary }
[Ordnance Survey data](ordnance_survey.md){ .md-button }
[API reference](api_reference.md){ .md-button }

[^1]: Timings on a MacBook Pro M4 Max.
[^2]: The `postcode` column is optional. If you include it, the matcher will use it directly. If you do not, the matcher will attempt to detect and extract postcodes from `address_concat`.  `uk_address_matcher` also supports matching addresses that lack a postcode.
