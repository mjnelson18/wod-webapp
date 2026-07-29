"""Repo-relative paths.

Resolved from WOD_REPO_ROOT when set (the local dev shim runs the package from a
staging directory, so it can't infer the repo from __file__), otherwise from this
file's location.
"""

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("WOD_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def reference_dir() -> Path:
    return repo_root() / "reference"


def historical_dir() -> Path:
    return reference_dir() / "historical"


def cache_dir() -> Path:
    return repo_root() / "pipeline" / "cache"


def data_dir() -> Path:
    return repo_root() / "data"


def season_data_dir(season: str) -> Path:
    return data_dir() / str(season)
