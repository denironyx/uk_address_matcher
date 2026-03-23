from __future__ import annotations

from pathlib import Path

from benchmarking.utils.io import apply_env_from_private_config, get_env_setting


def _with_trailing_slash(path: str) -> str:
    return path if path.endswith("/") else f"{path}/"


def resolve_data_path(env_var_path: str) -> str:
    """Resolve a dataset base path from a single environment variable.

    S3 paths must start with ``s3://``. Any non-S3 path is treated as local and
    must point to an existing directory.
    """
    apply_env_from_private_config()
    path = get_env_setting(env_var_path, default="").strip()
    if not path:
        raise RuntimeError(f"{env_var_path} must be set to a non-empty data path.")

    if path.startswith("s3://"):
        return _with_trailing_slash(path.rstrip("/"))

    local_path = Path(path).expanduser()
    if not local_path.exists() or not local_path.is_dir():
        raise RuntimeError(
            f"{env_var_path} points to '{local_path}', but that local directory "
            "does not exist."
        )

    return _with_trailing_slash(local_path.as_posix().rstrip("/"))
