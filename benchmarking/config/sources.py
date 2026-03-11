from __future__ import annotations

import os

from benchmarking.utils.io import apply_env_from_private_config, get_env_setting


def resolve_s3_path(env_var_explicit: str, env_var_relative: str) -> str:
    """Resolve an S3 path from environment variables.

    First checks for an explicit full path in ``env_var_explicit``.
    If not set, constructs a path from ``UKAM_S3_BASE_PREFIX`` and
    ``env_var_relative``.
    """
    apply_env_from_private_config()
    explicit = os.getenv(env_var_explicit)
    if explicit is not None and explicit.strip():
        path = explicit.strip().rstrip("/")
    else:
        prefix = get_env_setting("UKAM_S3_BASE_PREFIX", default="")
        relative = get_env_setting(env_var_relative, default="")
        if not prefix.strip() or not relative.strip():
            raise RuntimeError(
                f"Either {env_var_explicit} must be set to a full path, or both "
                "UKAM_S3_BASE_PREFIX and "
                f"{env_var_relative} must be set to construct the path."
            )
        path = f"{prefix.strip().rstrip('/')}/{relative.strip().lstrip('/')}"

    return path if path.endswith("/") else f"{path}/"
