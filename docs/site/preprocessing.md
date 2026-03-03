# Pre-processing large datasets

Use pre-processing when your canonical dataset is large (for example, national-scale AddressBase). It computes reusable artefacts once, so subsequent matching runs are fast and avoid heavy on-the-fly cleaning.

## One-time pre-processing

```python
import duckdb
from uk_address_matcher import prepare_canonical_folder

con = duckdb.connect()
df_canonical = con.read_parquet("data/output/*.parquet")

prepare_canonical_folder(
    df_canonical,
    output_folder="./ukam_prepared_canonical",
    con=con,
    overwrite=True,
)
```

## How to load it in for matching

Pass the folder path to `AddressMatcher` via `canonical_addresses`:

```python
import duckdb
from uk_address_matcher import AddressMatcher

con = duckdb.connect()
df_messy = con.read_parquet("messy_addresses.parquet")

matcher = AddressMatcher(
    canonical_addresses="./ukam_prepared_canonical",
    addresses_to_match=df_messy,
    con=con,
)

result = matcher.match()
```

Optional: restrict canonical records at load time with a SQL filter:

```python
matcher = AddressMatcher(
    canonical_addresses="./ukam_prepared_canonical",
    addresses_to_match=df_messy,
    con=con,
    canonical_address_filter="lowertierlocalauthoritygsscode = 'E09000012'",
)
```


## What it writes

`prepare_canonical_folder` writes these files into your output folder:

- `ukam_canonical_addresses.parquet` — cleaned/tokenised canonical addresses
- `ukam_term_frequencies.parquet` — term-frequency lookup table
- `ukam_inverted_index.parquet` — inverted index used for candidate retrieval
- `ukam_manifest.json` — metadata (package version, row counts, file hashes)