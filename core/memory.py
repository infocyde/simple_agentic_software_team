"""Memory Manager - Handles persistent context and memory for projects."""

import os
import re
import json
from datetime import datetime
from typing import Dict, Any, List, Optional


class MemoryManager:
    """
    Manages persistent memory for a project.
    Keeps context minimal and focused to reduce token usage.

    Memory is stored in MEMORY.md within the project directory.
    """

    def __init__(self, project_path: str, config: Optional[Dict[str, Any]] = None):
        self.project_path = project_path
        self.memory_file = os.path.join(project_path, "MEMORY.md")
        self._file_cache: Dict[str, Dict[str, Any]] = {}
        memory_config = (config or {}).get('memory', {})
        self.max_action_log_entries = memory_config.get('max_action_log_entries', 15)
        self._ensure_memory_file()

    def _ensure_memory_file(self):
        """Create memory file if it doesn't exist."""
        if not os.path.exists(self.memory_file):
            os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
            with open(self.memory_file, 'w') as f:
                f.write("# Project Memory\n\n")
                f.write("This file tracks decisions, actions, and lessons learned.\n\n")
                f.write("## Decisions\n\n")
                f.write("## Actions Log\n\n")
                f.write("## Lessons Learned\n\n")

    def record_decision(self, decision: str, rationale: str):
        """Record a key decision and its rationale."""
        with open(self.memory_file, 'r') as f:
            content = f.read()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- [{timestamp}] **{decision}**: {rationale}\n"

        # Insert after ## Decisions header
        marker = "## Decisions\n"
        if marker in content:
            pos = content.find(marker) + len(marker)
            # Find the next line after the header
            next_newline = content.find("\n", pos)
            if next_newline != -1:
                content = content[:next_newline+1] + entry + content[next_newline+1:]

        with open(self.memory_file, 'w') as f:
            f.write(content)

    def record_action(self, agent: str, task: str, result: str):
        """Record an action taken by an agent, capping at max_action_log_entries."""
        with open(self.memory_file, 'r') as f:
            content = f.read()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        # Keep action logs brief
        brief_result = result[:200] + "..." if len(result) > 200 else result
        entry = f"- [{timestamp}] **{agent}**: {task[:100]}\n  - Result: {brief_result}\n"

        # Insert after ## Actions Log header and prune old entries
        marker = "## Actions Log\n"
        if marker in content:
            pos = content.find(marker) + len(marker)
            # Find the end of the Actions Log section (next ## header or EOF)
            end_marker = "## Lessons Learned"
            end_pos = content.find(end_marker, pos) if end_marker in content[pos:] else len(content)

            section_before = content[:pos]
            section_after = content[end_pos:]
            actions_block = content[pos:end_pos]

            # Parse existing entries (each starts with "- [")
            entries = []
            current_entry = []
            for line in actions_block.split('\n'):
                if line.startswith('- ['):
                    if current_entry:
                        entries.append('\n'.join(current_entry))
                    current_entry = [line]
                elif current_entry and line.strip():
                    current_entry.append(line)
                elif current_entry:
                    entries.append('\n'.join(current_entry))
                    current_entry = []
            if current_entry:
                entries.append('\n'.join(current_entry))

            # Prepend new entry and cap at MAX_ACTION_LOG_ENTRIES
            entries.insert(0, entry.rstrip())
            entries = entries[:self.max_action_log_entries]

            content = section_before + '\n' + '\n'.join(entries) + '\n\n' + section_after

        with open(self.memory_file, 'w') as f:
            f.write(content)

    def record_lesson(self, lesson: str):
        """Record a lesson learned for future reference."""
        with open(self.memory_file, 'r') as f:
            content = f.read()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- [{timestamp}] {lesson}\n"

        marker = "## Lessons Learned\n"
        if marker in content:
            pos = content.find(marker) + len(marker)
            next_newline = content.find("\n", pos)
            if next_newline != -1:
                content = content[:next_newline+1] + entry + content[next_newline+1:]

        with open(self.memory_file, 'w') as f:
            f.write(content)

    def get_context_for_task(self, task: str, section: Optional[str] = None) -> str:
        """
        Get minimal, relevant context for a specific task.
        Keeps token usage low — the agent can read SPEC.md/TODO.md itself if needed.

        Args:
            task: The task text
            section: Optional section name to filter TODO tasks (e.g., "## Setup")
        """
        context_parts = []

        # Include recent decisions (last 2) — minimal but high-value for architectural guidance
        decisions = self._get_recent_decisions(2)
        if decisions:
            context_parts.append("Recent decisions:\n" + "\n".join(decisions))

        # Include a few sibling tasks from the same section for awareness (max 3).
        # Skip if no section specified — the agent doesn't need random unrelated tasks.
        if section:
            todo_path = os.path.join(self.project_path, "TODO.md")
            todo_content = self._read_file_cached(todo_path)
            if todo_content is not None:
                filtered_todo = self._filter_todo_for_section(todo_content, section)
                if filtered_todo:
                    context_parts.append(f"Other tasks in this section:\n{filtered_todo}")

        return "\n\n".join(context_parts) if context_parts else ""

    # Pattern to strip {ID} prefix and [depends: ...] suffix from task lines
    _TASK_METADATA_RE = re.compile(
        r'(?:\{\d+\}\s*)'           # optional {ID} prefix
        r'|'
        r'(?:\s*\[depends:\s*[\d,\s]+\])'  # optional [depends: ...] suffix
    )

    def _clean_task_line(self, line: str) -> str:
        """Strip {ID} and [depends: ...] metadata from a TODO line.

        Agents don't need internal bookkeeping metadata — it confuses them
        and wastes tokens.  Return just the human-readable task text.
        """
        return self._TASK_METADATA_RE.sub('', line).strip()

    def _filter_todo_for_section(self, todo_content: str, section: Optional[str]) -> str:
        """
        Filter TODO.md to only include uncompleted tasks from the specified section.
        This reduces token usage by excluding completed tasks and unrelated sections.
        Strips internal metadata ({ID}, [depends:]) so agents see clean task text.
        """
        lines = todo_content.split('\n')

        # If no section specified, return one uncompleted task for minimal awareness
        if not section:
            uncompleted = [self._clean_task_line(line) for line in lines if '[ ]' in line]
            return uncompleted[0] if uncompleted else ''

        # Normalize section name for matching
        section_normalized = section.lower().strip()
        if not section_normalized.startswith('##'):
            section_normalized = '## ' + section_normalized.lstrip('#').strip()

        # Find the section and extract uncompleted tasks
        in_target_section = False
        section_tasks = []

        for line in lines:
            # Check for section headers
            if line.strip().startswith('##'):
                # Check if this is our target section
                if section_normalized in line.lower() or line.lower().strip().startswith(section_normalized):
                    in_target_section = True
                else:
                    in_target_section = False
                continue

            # If in target section, collect uncompleted tasks only
            if in_target_section and '[ ]' in line:
                section_tasks.append(self._clean_task_line(line))

        return '\n'.join(section_tasks)

    def get_project_summary(self) -> str:
        """Get a brief summary of the project state."""
        summary_parts = []

        # Spec exists?
        spec_path = os.path.join(self.project_path, "SPEC.md")
        if os.path.exists(spec_path):
            summary_parts.append("- SPEC.md exists")

        # TODO status
        todo_path = os.path.join(self.project_path, "TODO.md")
        todo = self._read_file_cached(todo_path)
        if todo is not None:
            completed = todo.count("[x]")
            total = todo.count("[ ]") + completed
            summary_parts.append(f"- TODO: {completed}/{total} tasks completed")

        # Memory entries
        memory = self._read_file_cached(self.memory_file)
        if memory is not None:
            decision_count = memory.count("**") // 2  # rough count
            summary_parts.append(f"- Memory: ~{decision_count} decisions recorded")

        return "\n".join(summary_parts) if summary_parts else "New project - no history yet"

    def _get_recent_decisions(self, count: int) -> List[str]:
        """Get the most recent decisions."""
        content = self._read_file_cached(self.memory_file)
        if content is None:
            return []

        decisions = []
        marker = "## Decisions\n"
        end_marker = "## Actions Log"

        if marker in content:
            start = content.find(marker) + len(marker)
            end = content.find(end_marker) if end_marker in content else len(content)
            decisions_section = content[start:end].strip()

            for line in decisions_section.split("\n"):
                if line.startswith("- ["):
                    decisions.append(line)
                    if len(decisions) >= count:
                        break

        return decisions

    def _read_file_cached(self, path: str) -> Optional[str]:
        """Read a file with a simple mtime-based cache to reduce disk I/O."""
        try:
            if not os.path.exists(path):
                # Clear cache entry if file was removed
                if path in self._file_cache:
                    del self._file_cache[path]
                return None

            mtime = os.path.getmtime(path)
            cached = self._file_cache.get(path)
            if cached and cached.get("mtime") == mtime:
                return cached.get("content")

            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            self._file_cache[path] = {"mtime": mtime, "content": content}
            return content
        except Exception:
            return None

    def clear_memory(self):
        """Clear all memory (use with caution)."""
        self._ensure_memory_file()
        with open(self.memory_file, 'w') as f:
            f.write("# Project Memory\n\n")
            f.write("This file tracks decisions, actions, and lessons learned.\n\n")
            f.write("## Decisions\n\n")
            f.write("## Actions Log\n\n")
            f.write("## Lessons Learned\n\n")
