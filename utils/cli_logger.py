"""Shared logger for Claude CLI calls - appends entries to {project_path}/log.md."""

import os
import aiofiles
from datetime import datetime


async def log_cli_call(
    project_path: str,
    agent_name: str,
    agent_role: str,
    prompt: str,
    model: str,
    status: str,
    result_summary: str = ""
):
    """Append a CLI call entry to {project_path}/log.md."""
    log_path = os.path.join(project_path, "log.md")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    prompt_preview = prompt.replace('\n', '\n> ')
    result_preview = result_summary if result_summary else "(no output)"

    entry = f"""
## {timestamp}
- **Agent:** {agent_name} ({agent_role})
- **Model:** {model or 'default'}
- **Status:** {status}
- **Prompt (preview):**
> {prompt_preview}

- **Result (preview):** {result_preview}
---
"""
    try:
        if os.path.exists(log_path):
            async with aiofiles.open(log_path, 'a', encoding='utf-8') as f:
                await f.write(entry)
        else:
            async with aiofiles.open(log_path, 'w', encoding='utf-8') as f:
                await f.write("# Claude CLI Call Log\n\nAll Claude Code CLI invocations for this project.\n\n---\n")
                await f.write(entry)
    except Exception:
        pass  # Never fail the actual task due to logging
