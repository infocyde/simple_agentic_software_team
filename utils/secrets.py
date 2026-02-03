"""Utilities for loading project secrets from env files."""

from __future__ import annotations

import os
from typing import Dict, Optional

from dotenv import dotenv_values


def _load_env_file(path: str) -> Dict[str, str]:
    """Load non-empty values from an env file, skipping keys already in os.environ."""
    if not os.path.exists(path):
        return {}

    values = dotenv_values(path)
    secrets: Dict[str, str] = {}
    for key, value in values.items():
        if not key or value is None:
            continue
        if key in os.environ:
            continue
        secrets[key] = value

    return secrets


def load_project_secrets(project_path: Optional[str] = None) -> Dict[str, str]:
    """Load secrets from global and project-level env files.

    Loads from two locations (in order, later values win):
      1. Global:  secrets/.env  (tool-level, shared across all projects)
      2. Project: {project_path}/.env  (project-specific overrides)

    Only returns values that are non-empty and not already set in the environment.
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    global_path = os.path.join(base_dir, "secrets", ".env")

    secrets = _load_env_file(global_path)

    if project_path:
        project_env_path = os.path.join(project_path, ".env")
        secrets.update(_load_env_file(project_env_path))

    return secrets
