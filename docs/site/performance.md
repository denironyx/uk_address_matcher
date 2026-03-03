# Performance overview

## Timings

Indicative timings for matching 100,000 messy addresses are as follows.

Note that runtimes depend on whether the canonical data covers a local council region or the whole UK.

| Task | Local council region | Full country |
|------|---------------------|--------------|
| 1. Create data package and API key | 5 minutes | 5 minutes |
| 2. Install Python, uv, and `uk_address_matcher` | 5 minutes | 5 minutes |
| 3. Download and process OS data into a flat file | 5 seconds[^1] | 4 minutes[^2] |
| 4. Pre-process indexes and features | Not necessary | 4 min 50 sec |
| 5. Match 100,000 records | 26 seconds | 46 seconds |

[^1]: Plus ~15 seconds to download the data.
[^2]: Plus ~18 minutes to download the data.

These timings are measured on a MacBook Pro M4 Max.

Steps 1–3 are one-off; subsequent matching runs only require step 5 (or steps 4–5 for the full UK dataset).

## Benchmarking

There many different address matching solutions and it can be hard to compare performance between them.

Luckily, there are several open datasets of labelled address data that can be used to benchmark accuracy.

In this section, we set out `uk_address_matcher`'s accuracy against these labelled datasets.


### Hackney Council data

The Hackney Council dataset is available from https://www.datadaptive.com/addr/.


<details>
  <summary>Expand to see Hackney benchmarking script</summary>

```python
import pyarrow as pa
import duckdb
from uk_address_matcher import AddressMatcher, ExactMatchStage, SplinkStage
import uk_address_matcher


import time
import logging


start_time = time.time()
con = duckdb.connect()

path_to_all_canonical = "path_to_output_from_ukam-os-builder_tool"

sql = f"""
select *
from read_parquet('{path_to_all_canonical}')
where lowertierlocalauthoritygsscode = 'E09000012'
and substr(classificationcode, 1, 1) = 'R'
"""
df_canonical = con.sql(sql)


path = "path_to_HACKNEY_CTBANDS_ONSUD_202507.csv"
raw_labelled_data = con.read_csv(path)
raw_labelled_data.count("*").show()


sql = """
select propref as unique_id,
concat_ws(' ', addr1, addr2, addr3, addr4) as address_concat,
uprn as ukam_label,
postcode
from raw_labelled_data
where uprn is not null
and uprn in (select unique_id from df_canonical)

"""
df_messy = con.sql(sql)
df_messy.count("*").show()


matcher = AddressMatcher(
    canonical_addresses=df_canonical,
    addresses_to_match=df_messy,
    con=con,
    stages=[
        ExactMatchStage(),
        SplinkStage(
            final_distinguishability_threshold=1,
        ),
    ],
)

result = matcher.match()

end_time = time.time()
print(f"Execution time: {end_time - start_time} seconds")

chart = result.accuracy_analysis(output_type="precision_recall", add_metrics=["f1"], match_weight_round_to_nearest=1)
accuracy_table = result.accuracy_analysis(output_type="table", add_metrics=["f1"], match_weight_round_to_nearest= 1)

df = pa.Table.from_pylist(accuracy_table)
con.sql("select * from df").show(max_width=100000, max_rows=100000)
```

Note that we:
- Filter out any rows from the messy dataset where the label UPRN does not exist in our canonical dataset. We could not be expected to match these
- Filter the canonical dataset down to the Hackney council region, and to residential properties.

</details>

This script takes 26 seconds to run against 114,544 labelled records.

It achieves:

- 99.6% precision with recall of 71%
- 99.0% precision with recall of 94%

The full precision-recall curve is shown below:

```vegalite
{
    "schema-url": "assets/charts/hackney_precision_recall.json"
}
```

Manual review of the 'false positives' suggests many may in fact be true positives (that the "ground truth" labels contains errors).  So the true precision is likely higher than indicated in this chart.