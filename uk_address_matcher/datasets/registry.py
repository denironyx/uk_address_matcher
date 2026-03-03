from __future__ import annotations

import os

from uk_address_matcher.datasets.specs import DatasetSpec

DEFAULT_DATASETS_BASE_URL = (
    "https://raw.githubusercontent.com/robinL/uk_address_matcher/main/example_data"
)
DATASETS_BASE_URL_ENV = "UKAM_DATASETS_BASE_URL"


def default_base_url() -> str:
    return os.getenv(DATASETS_BASE_URL_ENV, DEFAULT_DATASETS_BASE_URL)


def build_default_specs() -> list[DatasetSpec]:
    base_url = default_base_url()
    return [
        DatasetSpec(
            name="canonical_example",
            file_name="canonical_example.csv",
            base_url=base_url,
        ),
        DatasetSpec(
            name="messy_example",
            file_name="messy_example.csv",
            base_url=base_url,
        ),
        DatasetSpec(
            name="fictional_london_canonical",
            file_name="fictional_london_canonical.parquet",
            base_url=base_url,
        ),
        DatasetSpec(
            name="fictional_london_messy",
            file_name="fictional_london_messy.parquet",
            base_url=base_url,
        ),
    ]
