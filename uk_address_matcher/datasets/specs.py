from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    file_name: str
    base_url: str

    @property
    def url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.file_name}"
