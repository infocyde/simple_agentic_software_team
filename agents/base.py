"""Base agent class that all specialized agents inherit from - uses Claude Code CLI."""

import os
import sys
import json
import asyncio
import signal
import subprocess
import tempfile
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
from utils.cli_logger import log_cli_call


class BaseAgent(ABC):
    """
    Base class for all agents in the team.
    Uses Claude Code CLI for execution, leveraging your existing subscription.
    """

    # Keywords that suggest a task needs more reasoning power (use Opus)
    # Keep this list tight - only truly complex tasks
    COMPLEX_KEYWORDS = [
        'architect', 'debug', 'security', 'vulnerability', 'review',
        'refactor', 'optimize', 'investigate', 'complex',
        'integrate', 'migrate', 'authentication', 'authorization', 'encryption'
    ]

    # Keywords that suggest a straightforward task (use Sonnet)
    # Expanded - most implementation work is straightforward
    SIMPLE_KEYWORDS = [
        'create', 'write', 'add', 'update', 'edit', 'rename', 'delete', 'remove',
        'css', 'style', 'html', 'template', 'component', 'page', 'view',
        'copy', 'move', 'format', 'install', 'run', 'execute', 'build', 'test',
        'lint', 'implement', 'setup', 'configure', 'endpoint', 'route', 'api',
        'model', 'schema', 'migration', 'seed', 'fixture', 'mock',
        'button', 'form', 'input', 'list', 'table', 'card', 'modal', 'navbar',
        'function', 'method', 'class', 'module', 'import', 'export'
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
        self.stream_callback: Optional[Callable] = None  # Set by orchestrator for debug mode
        self.conversation_history: List[Dict[str, Any]] = []
        # Session continuity: reuse Claude CLI sessions across tasks
        self._session_id: Optional[str] = None
        self._session_continuity: bool = False  # Enabled via config

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

    def reset_session(self):
        """Clear the stored session ID, forcing a cold start on the next task."""
        self._session_id = None

    def _build_prompt(self, task: str, context: str = "", is_simple: bool = False) -> str:
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

        # Add minimal instructions — only items that change Claude's default behavior
        prompt_parts.append("## Instructions")
        prompt_parts.append("- Do NOT open or use Playwright browser tools unless your task specifically requires browser-based testing or visual verification. Writing code, running scripts, and running tests do NOT require a browser.")
        prompt_parts.append("- For external library docs: run `python utils/search_docs.py '<library> <topic>'` then use WebFetch to read results.")

        if is_simple:
            prompt_parts.append("- Be concise. Do not over-engineer, explore unrelated code, or add unnecessary abstractions.")

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

        # Decision logic - favor Sonnet for speed, Opus only when clearly needed
        if complex_score > simple_score and complex_score >= 2:
            return 'complex'
        else:
            # Default to simple (Sonnet) - fast and capable for most tasks
            return 'simple'

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
        timeout: int = 600,
        config: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Process a task using Claude Code CLI.

        Claude CLI handles all tool execution internally (file operations,
        running commands, etc.) so we just need to invoke it with the right prompt.
        """
        self.log_activity("Starting task", task[:100])

        # Enable session continuity if configured
        if config:
            self._session_continuity = config.get('execution', {}).get('session_continuity', False)

        # Determine which model to use
        model = self._get_model_for_task(task, config)

        # Apply complexity-based timeout with context-size awareness
        complexity = self._classify_task_complexity(task)
        if complexity == 'simple' and config:
            simple_timeout = config.get('execution', {}).get('simple_task_timeout_seconds', 300)
            effective_timeout = min(timeout, simple_timeout)
        else:
            effective_timeout = timeout

        # Extend timeout if the prompt + context is large (Claude needs more time
        # to process large contexts even for "simple" tasks)
        prompt_size = len(task) + len(context)
        if prompt_size > 5000:
            # Add 60s per 5K chars of context, up to doubling the timeout
            context_extension = min(effective_timeout, (prompt_size // 5000) * 60)
            effective_timeout += context_extension
            self.log_activity("Timeout adjusted", f"{effective_timeout}s (large context: {prompt_size} chars)")

        timeout = effective_timeout

        # Build the prompt (with urgency hint for simple tasks)
        prompt = self._build_prompt(task, context, is_simple=(complexity == 'simple'))

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

                await log_cli_call(
                    project_path=project_path,
                    agent_name=self.name,
                    agent_role=self.role,
                    prompt=prompt,
                    model=model or "default",
                    status="complete",
                    result_summary=result[:300] if result else ""
                )

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
            await log_cli_call(
                project_path=project_path,
                agent_name=self.name,
                agent_role=self.role,
                prompt=prompt,
                model=model or "default",
                status="timeout",
                result_summary=f"Task timed out after {timeout} seconds"
            )
            return {
                "status": "timeout",
                "result": f"Task timed out after {timeout} seconds",
                "agent": self.name
            }
        except Exception as e:
            self.log_activity("Task error", str(e))
            await log_cli_call(
                project_path=project_path,
                agent_name=self.name,
                agent_role=self.role,
                prompt=prompt,
                model=model or "default",
                status="error",
                result_summary=str(e)[:300]
            )
            return {
                "status": "error",
                "result": str(e),
                "agent": self.name
            }

    def _kill_process_tree(self, process):
        """Kill a process and all its children. Critical on Windows where
        terminate() only kills the parent, leaving child processes orphaned."""
        pid = process.pid
        try:
            if sys.platform == 'win32':
                # On Windows, use taskkill /T to kill the entire process tree
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10
                )
            else:
                # On Unix, kill the process group
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                # Fallback: kill the process directly
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
        except Exception:
            # Last resort: just try terminate
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    async def _run_claude_cli(self, prompt_file: str, working_dir: str, model: Optional[str] = None) -> str:
        """Run Claude CLI and return the output.

        Pipes prompt via stdin to avoid Windows command-line length limits.
        Uses process tree kill on timeout to avoid orphaned child processes.
        """

        # Read prompt from file
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()

        # Build the claude command
        # Using --print for non-interactive output
        # Using --dangerously-skip-permissions for autonomous operation
        # Using --output-format json to capture session_id for continuity
        # Prompt is piped via stdin (no command-line length limit)
        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--output-format", "json"
        ]

        # Session continuity: resume a previous session to avoid cold-start overhead
        resuming = False
        if self._session_continuity and self._session_id:
            cmd.extend(["--resume", self._session_id])
            resuming = True

        # Add model flag if specified
        if model:
            cmd.extend(["--model", model])

        session_info = f" (resuming session)" if resuming else " (new session)"
        model_info = f" (model: {model})" if model else ""
        self.log_activity("Invoking Claude CLI", f"Working dir: {working_dir}{model_info}{session_info}")

        # Set up environment with UTF-8 encoding for Windows compatibility
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        # On Windows, create a new process group so we can kill the tree on timeout.
        # On Unix, use start_new_session for the same effect.
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs['start_new_session'] = True

        # Encode prompt for stdin
        prompt_bytes = prompt_content.encode('utf-8')

        # Run the command with prompt piped via stdin
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=working_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            **kwargs
        )

        # Start heartbeat task to log progress
        heartbeat_task = asyncio.create_task(self._heartbeat_logger(process))

        try:
            if self.stream_callback:
                # Debug mode: write prompt to stdin, then stream output line-by-line
                process.stdin.write(prompt_bytes)
                await process.stdin.drain()
                process.stdin.close()
                output_lines = []
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    decoded = line.decode('utf-8', errors='replace')
                    output_lines.append(decoded)
                    try:
                        await self.stream_callback(self.name, decoded)
                    except Exception:
                        pass  # Never let streaming errors break the task
                await process.wait()
                output = ''.join(output_lines)
                # Still capture stderr
                stderr_data = await process.stderr.read()
                if stderr_data:
                    error_output = stderr_data.decode('utf-8', errors='replace')
                    if error_output.strip():
                        output += f"\n\nStderr:\n{error_output}"
            else:
                # Normal mode: pipe prompt via stdin and wait for full output
                stdout, stderr = await process.communicate(input=prompt_bytes)
                output = stdout.decode('utf-8', errors='replace')
                if stderr:
                    error_output = stderr.decode('utf-8', errors='replace')
                    if error_output.strip():
                        output += f"\n\nStderr:\n{error_output}"
        except asyncio.CancelledError:
            # Kill the entire process tree, not just the parent
            self._kill_process_tree(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                # Process didn't exit after tree kill, force terminate
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            raise
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        # Parse JSON output to extract result text and session_id.
        # --output-format json wraps the response in a JSON envelope.
        output = self._parse_cli_json_output(output)

        # Clean any problematic characters that might cause issues downstream
        output = self._sanitize_output(output)

        return output

    async def _heartbeat_logger(self, process):
        """Log periodic heartbeat messages while a process is running."""
        elapsed = 0
        interval = 45  # Log every 45 seconds
        try:
            while process.returncode is None:
                await asyncio.sleep(interval)
                elapsed += interval
                minutes = elapsed // 60
                seconds = elapsed % 60
                if minutes > 0:
                    time_str = f"{minutes}m {seconds}s"
                else:
                    time_str = f"{seconds}s"
                self.log_activity("Still working...", f"Elapsed: {time_str}")
        except asyncio.CancelledError:
            pass

    def _parse_cli_json_output(self, raw_output: str) -> str:
        """Parse JSON envelope from --output-format json and extract the result text.

        Also captures the session_id for session continuity on subsequent calls.
        Falls back to returning raw output if JSON parsing fails.
        """
        if not raw_output or not raw_output.strip():
            return raw_output

        try:
            # The JSON output may contain stderr noise before the JSON object.
            # Find the first '{' to locate the JSON start.
            trimmed = raw_output.strip()
            json_start = trimmed.find('{')
            if json_start == -1:
                return raw_output
            data = json.loads(trimmed[json_start:])

            # Capture session_id for continuity
            sid = data.get("session_id")
            if sid and self._session_continuity:
                if self._session_id != sid:
                    self.log_activity("Session tracked", f"ID: {sid[:12]}...")
                self._session_id = sid

            # If the CLI reported an error, reset session (it may be stale)
            if data.get("is_error"):
                self.log_activity("Session reset", "CLI reported error; clearing session")
                self._session_id = None

            # Return the result text, falling back to raw output
            return data.get("result", raw_output)
        except (json.JSONDecodeError, TypeError, ValueError):
            # Not valid JSON — could be an error message or legacy plain-text output.
            # If we were resuming and got a non-JSON error, the session may be stale.
            if self._session_id:
                self.log_activity("Session reset", "Non-JSON response; clearing stale session")
                self._session_id = None
            return raw_output

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
