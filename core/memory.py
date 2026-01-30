"""Memory Manager - Handles persistent context and memory for projects."""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional


class MemoryManager:
    """
    Manages persistent memory for a project.
    Keeps context minimal and focused to reduce token usage.

    Memory is stored in MEMORY.md within the project directory.
    """

    def __init__(self, project_path: str):
        self.project_path = project_path
        self.memory_file = os.path.join(project_path, "MEMORY.md")
        self._file_cache: Dict[str, Dict[str, Any]] = {}
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
        """Record an action taken by an agent."""
        with open(self.memory_file, 'r') as f:
            content = f.read()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        # Keep action logs brief
        brief_result = result[:200] + "..." if len(result) > 200 else result
        entry = f"- [{timestamp}] **{agent}**: {task[:100]}\n  - Result: {brief_result}\n"

        # Insert after ## Actions Log header
        marker = "## Actions Log\n"
        if marker in content:
            pos = content.find(marker) + len(marker)
            next_newline = content.find("\n", pos)
            if next_newline != -1:
                content = content[:next_newline+1] + entry + content[next_newline+1:]

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

        # Include recent decisions (last 5) — small and high-value for architectural guidance
        decisions = self._get_recent_decisions(5)
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

        return "\n\n---\n\n".join(context_parts) if context_parts else ""

    def _filter_todo_for_section(self, todo_content: str, section: Optional[str]) -> str:
        """
        Filter TODO.md to only include uncompleted tasks from the specified section.
        This reduces token usage by excluding completed tasks and unrelated sections.
        """
        lines = todo_content.split('\n')

        # If no section specified, return a few uncompleted tasks for minimal awareness
        if not section:
            uncompleted = [line for line in lines if '[ ]' in line]
            return '\n'.join(uncompleted[:3])

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
                section_tasks.append(line)

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
