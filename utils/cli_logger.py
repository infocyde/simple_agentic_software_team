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

    Logs the full prompt and full result so the log accurately reflects
    what was sent to and received from Claude.
    """
    log_path = os.path.join(project_path, "log.md")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    prompt_quoted = prompt.replace('\n', '\n> ')
    result_text = result_summary if result_summary else "(no output)"

    # Session info line
    session_info = ""
    if resuming:
        session_info = "- **Session:** resumed (agent definition skipped)\n"
    if context_window_max > 0:
        usage_pct = (session_chars_used / context_window_max * 100) if context_window_max else 0
        session_info += f"- **Context usage:** ~{session_chars_used:,} / {context_window_max:,} chars ({usage_pct:.0f}%)\n"

    entry = f"""
## {timestamp}
- **Agent:** {agent_name} ({agent_role})
- **Model:** {model or 'default'}
- **Status:** {status}
{session_info}- **Prompt:**
> {prompt_quoted}

- **Result:**
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
