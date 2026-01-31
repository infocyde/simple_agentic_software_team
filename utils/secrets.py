"""Utilities for loading per-agent secrets from local env files."""

from __future__ import annotations

import os
from typing import Dict

from dotenv import dotenv_values


def load_agent_secrets(agent_name: str) -> Dict[str, str]:
    """Load secrets for a specific agent from secrets/{agent_name}.env.

    Only returns values that are non-empty and not already set in the environment.
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    secrets_path = os.path.join(base_dir, "secrets", f"{agent_name}.env")

    if not os.path.exists(secrets_path):
        return {}

    values = dotenv_values(secrets_path)
    secrets: Dict[str, str] = {}
    for key, value in values.items():
        if not key or value is None:
            continue
        if key in os.environ:
            continue
        secrets[key] = value

    return secrets
