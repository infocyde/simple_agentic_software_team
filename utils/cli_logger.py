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
    result_summary: str = "",
    resuming: bool = False,
    session_chars_used: int = 0,
    context_window_max: int = 0
):
    """Append a CLI call entry to {project_path}/log.md.

    Logs truncated prompt/result to reduce disk bloat while preserving debuggability.
    """
    log_path = os.path.join(project_path, "log.md")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Truncate prompt and result to reduce log size (full versions rarely needed)
    prompt_truncated = prompt[:500] + "..." if len(prompt) > 500 else prompt
    prompt_quoted = prompt_truncated.replace('\n', '\n> ')
    result_text = result_summary[:300] + "..." if len(result_summary) > 300 else (result_summary or "(no output)")

    # Minimal session info
    session_info = ""
    if context_window_max > 0:
        usage_pct = (session_chars_used / context_window_max * 100) if context_window_max else 0
        session_info = f"- **Context:** {usage_pct:.0f}%\n"

    entry = f"""
## {timestamp}
- **Agent:** {agent_name}
- **Model:** {model or 'default'}
- **Status:** {status}
{session_info}> {prompt_quoted}

{result_text}
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
