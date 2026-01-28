"""Base agent class that all specialized agents inherit from - uses Claude Code CLI."""

import os
import json
import asyncio
import subprocess
import tempfile
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime


class BaseAgent(ABC):
    """
    Base class for all agents in the team.
    Uses Claude Code CLI for execution, leveraging your existing subscription.
    """

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str = "",
        activity_callback: Optional[Callable] = None
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.activity_callback = activity_callback
        self.conversation_history: List[Dict[str, Any]] = []

    def log_activity(self, action: str, details: str = ""):
        """Log agent activity for the activity feed."""
        activity = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "role": self.role,
            "action": action,
            "details": details
        }
        if self.activity_callback:
            self.activity_callback(activity)
        return activity

    def _build_prompt(self, task: str, context: str = "") -> str:
        """Build the full prompt for Claude CLI."""
        prompt_parts = []

        # Add role context
        prompt_parts.append(f"You are the {self.role} on a software development team.")
        prompt_parts.append("")

        # Add system prompt (agent personality/instructions)
        if self.system_prompt:
            prompt_parts.append(self.system_prompt)
            prompt_parts.append("")

        # Add project context if provided
        if context:
            prompt_parts.append("## Current Context")
            prompt_parts.append(context)
            prompt_parts.append("")

        # Add the task
        prompt_parts.append("## Your Task")
        prompt_parts.append(task)
        prompt_parts.append("")

        # Add completion instructions
        prompt_parts.append("## Instructions")
        prompt_parts.append("- Complete the task described above")
        prompt_parts.append("- Use the available tools (read/write files, run commands) as needed")
        prompt_parts.append("- When finished, provide a brief summary of what you accomplished")
        prompt_parts.append("- If you encounter issues you cannot resolve, explain what went wrong")

        return "\n".join(prompt_parts)

    async def process_task(
        self,
        task: str,
        project_path: str,
        context: str = "",
        orchestrator: Any = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Process a task using Claude Code CLI.

        Claude CLI handles all tool execution internally (file operations,
        running commands, etc.) so we just need to invoke it with the right prompt.
        """
        self.log_activity("Starting task", task[:100])

        # Build the prompt
        prompt = self._build_prompt(task, context)

        try:
            # Write prompt to temp file to avoid shell escaping issues
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(prompt)
                prompt_file = f.name

            try:
                # Invoke Claude CLI with print mode
                # --print: non-interactive, outputs result
                # --dangerously-skip-permissions: allows autonomous operation
                result = await asyncio.wait_for(
                    self._run_claude_cli(prompt_file, project_path),
                    timeout=timeout
                )

                self.log_activity("Task complete", result[:100] if result else "No output")

                return {
                    "status": "complete",
                    "result": result,
                    "agent": self.name
                }

            finally:
                # Clean up temp file
                if os.path.exists(prompt_file):
                    os.unlink(prompt_file)

        except asyncio.TimeoutError:
            self.log_activity("Task timeout", f"Exceeded {timeout}s")
            return {
                "status": "timeout",
                "result": f"Task timed out after {timeout} seconds",
                "agent": self.name
            }
        except Exception as e:
            self.log_activity("Task error", str(e))
            return {
                "status": "error",
                "result": str(e),
                "agent": self.name
            }

    async def _run_claude_cli(self, prompt_file: str, working_dir: str) -> str:
        """Run Claude CLI and return the output."""

        # Read prompt from file
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()

        # Build the claude command
        # Using --print for non-interactive output
        # Using --dangerously-skip-permissions for autonomous operation
        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            prompt_content
        ]

        self.log_activity("Invoking Claude CLI", f"Working dir: {working_dir}")

        # Run the command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        output = stdout.decode('utf-8', errors='replace')
        if stderr:
            error_output = stderr.decode('utf-8', errors='replace')
            if error_output.strip():
                output += f"\n\nStderr:\n{error_output}"

        return output

    async def ask_question(
        self,
        question: str,
        project_path: str,
        timeout: int = 60
    ) -> str:
        """
        Ask a single question and get a response.
        Used for kickoff questions and clarifications.
        """
        prompt = f"""You are the {self.role}.

Please ask the following question to gather requirements:

{question}

Just output the question naturally, as if speaking to a colleague. Be concise."""

        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(prompt)
                prompt_file = f.name

            try:
                result = await asyncio.wait_for(
                    self._run_claude_cli(prompt_file, project_path),
                    timeout=timeout
                )
                return result.strip()
            finally:
                if os.path.exists(prompt_file):
                    os.unlink(prompt_file)

        except Exception as e:
            return f"Error: {str(e)}"

    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """Return a list of this agent's capabilities."""
        pass
