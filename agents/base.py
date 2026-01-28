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

    # Keywords that suggest a task needs more reasoning power (use Opus)
    COMPLEX_KEYWORDS = [
        'architect', 'design', 'debug', 'security', 'review', 'analyze',
        'refactor', 'optimize', 'why', 'explain', 'investigate', 'complex',
        'integrate', 'migrate', 'plan', 'strategy', 'decision', 'tradeoff',
        'authentication', 'authorization', 'encryption', 'vulnerability'
    ]

    # Keywords that suggest a straightforward task (use Sonnet)
    SIMPLE_KEYWORDS = [
        'create file', 'write', 'add', 'update', 'edit', 'rename', 'delete',
        'css', 'style', 'html', 'template', 'copy', 'move', 'format',
        'install', 'run', 'execute', 'build', 'test', 'lint'
    ]

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str = "",
        activity_callback: Optional[Callable] = None,
        model_preference: str = "auto"
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.activity_callback = activity_callback
        self.model_preference = model_preference  # "auto", "opus", or "sonnet"
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

    def _classify_task_complexity(self, task: str) -> str:
        """
        Classify task complexity to determine which model to use.
        Returns: 'simple' (use Sonnet) or 'complex' (use Opus)
        """
        task_lower = task.lower()

        # Check for complex keywords first (these take priority)
        complex_score = sum(1 for kw in self.COMPLEX_KEYWORDS if kw in task_lower)

        # Check for simple keywords
        simple_score = sum(1 for kw in self.SIMPLE_KEYWORDS if kw in task_lower)

        # If task is long or has multiple parts, lean toward Opus
        if len(task) > 500 or task.count('\n') > 10:
            complex_score += 2

        # Decision logic
        if complex_score > simple_score:
            return 'complex'
        elif simple_score > 0 and complex_score == 0:
            return 'simple'
        else:
            # Default to complex if unclear (safer)
            return 'complex'

    def _get_model_for_task(self, task: str, config: Optional[Dict] = None) -> Optional[str]:
        """
        Determine which model to use for this task.
        Returns model name or None to use CLI default.
        """
        # If model routing is disabled or no config, use default
        if not config:
            return None

        model_routing = config.get('model_routing', {})
        if not model_routing.get('enabled', False):
            return None

        # Check agent's model preference
        if self.model_preference == 'opus':
            return model_routing.get('models', {}).get('powerful')
        elif self.model_preference == 'sonnet':
            return model_routing.get('models', {}).get('fast')
        elif self.model_preference == 'auto':
            # Auto-classify based on task
            complexity = self._classify_task_complexity(task)
            if complexity == 'simple':
                model = model_routing.get('models', {}).get('fast')
                self.log_activity("Model selection", f"Using Sonnet (simple task)")
            else:
                model = model_routing.get('models', {}).get('powerful')
                self.log_activity("Model selection", f"Using Opus (complex task)")
            return model

        return None

    async def process_task(
        self,
        task: str,
        project_path: str,
        context: str = "",
        orchestrator: Any = None,
        timeout: int = 300,
        config: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Process a task using Claude Code CLI.

        Claude CLI handles all tool execution internally (file operations,
        running commands, etc.) so we just need to invoke it with the right prompt.
        """
        self.log_activity("Starting task", task[:100])

        # Determine which model to use
        model = self._get_model_for_task(task, config)

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
                    self._run_claude_cli(prompt_file, project_path, model=model),
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

    async def _run_claude_cli(self, prompt_file: str, working_dir: str, model: Optional[str] = None) -> str:
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
            "--dangerously-skip-permissions"
        ]

        # Add model flag if specified
        if model:
            cmd.extend(["--model", model])

        cmd.append(prompt_content)

        model_info = f" (model: {model})" if model else ""
        self.log_activity("Invoking Claude CLI", f"Working dir: {working_dir}{model_info}")

        # Set up environment with UTF-8 encoding for Windows compatibility
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        # Run the command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        stdout, stderr = await process.communicate()

        # Decode with error handling for special characters
        output = stdout.decode('utf-8', errors='replace')
        if stderr:
            error_output = stderr.decode('utf-8', errors='replace')
            if error_output.strip():
                output += f"\n\nStderr:\n{error_output}"

        # Clean any problematic characters that might cause issues downstream
        output = self._sanitize_output(output)

        return output

    def _sanitize_output(self, text: str) -> str:
        """Remove or replace characters that might cause encoding issues."""
        if not text:
            return text
        # Replace common problematic Unicode characters with ASCII equivalents
        replacements = {
            '\u2018': "'",  # Left single quote
            '\u2019': "'",  # Right single quote
            '\u201c': '"',  # Left double quote
            '\u201d': '"',  # Right double quote
            '\u2013': '-',  # En dash
            '\u2014': '--', # Em dash
            '\u2026': '...', # Ellipsis
            '\u00a0': ' ',  # Non-breaking space
        }
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        # Remove any remaining non-ASCII characters that might cause issues
        return text.encode('ascii', errors='replace').decode('ascii')

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
