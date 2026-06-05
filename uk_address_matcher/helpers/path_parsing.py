from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import duckdb


def is_uri_reference(path: str | Path) -> bool:
    """Return True when a path-like value is a URI string."""
    return isinstance(path, str) and bool(urlsplit(path).scheme)


def is_remote_folder_reference(folder: str | Path) -> bool:
    """Return True when a folder reference points to a remote URI."""
    return is_uri_reference(folder)


def is_path_like_input(value: object) -> bool:
    """Return True for a single supported path-like input."""
    return isinstance(value, (str, Path))


def is_sequence_of_path_like_inputs(value: object) -> bool:
    """Return True for a non-empty list of supported path-like inputs."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, (str, Path)) for item in value)
    )


def join_remote_path(base: str, name: str) -> str:
    """Join a remote base URI and relative artefact name."""
    return f"{base.rstrip('/')}/{name}"


def strip_uri_query_or_fragment(path: str) -> str:
    """Strip URI query parameters and fragments for suffix detection."""
    parsed = urlsplit(path)
    return parsed.path if parsed.scheme else path.split("?", 1)[0].split("#", 1)[0]


def infer_tabular_input_format(path: str | Path) -> str | None:
    """Infer the supported tabular format for a local path or URI."""
    stripped_path = strip_uri_query_or_fragment(str(path)).lower()
    if stripped_path.endswith(".parquet") or "*.parquet" in stripped_path:
        return "parquet"
    if stripped_path.endswith(".csv") or "*.csv" in stripped_path:
        return "csv"
    return None


def relative_remote_path(base: str, path: str) -> str:
    """Return the artefact path relative to a remote base URI."""
    prefix = f"{base.rstrip('/')}/"
    if path.startswith(prefix):
        return path[len(prefix) :]
    return path


def read_duckdb_relation_from_path(
    path_or_paths: str | Path | list[str | Path],
    *,
    con: duckdb.DuckDBPyConnection,
) -> duckdb.DuckDBPyRelation:
    """Read CSV or Parquet path input(s) through DuckDB."""
    paths = [path_or_paths] if is_path_like_input(path_or_paths) else path_or_paths
    path_strings = [str(path) for path in paths]
    formats = {infer_tabular_input_format(path) for path in path_strings}

    if None in formats:
        raise ValueError(
            "Unsupported canonical input file type. Expected CSV or Parquet path(s)."
        )
    if len(formats) != 1:
        raise ValueError(
            "Canonical input path list must use a single file type. "
            "Mixing CSV and Parquet inputs is not supported."
        )

    read_input: str | list[str] = (
        path_strings[0] if len(path_strings) == 1 else path_strings
    )
    input_format = next(iter(formats))
    if input_format == "parquet":
        return con.read_parquet(read_input)
    return con.read_csv(read_input)
