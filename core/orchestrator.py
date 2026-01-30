"""Orchestrator - Coordinates the agent team and manages task flow."""

import os
import re
import json
import asyncio
import aiofiles
from typing import Dict, Any, List, Optional, Callable, Set
from datetime import datetime
from enum import Enum

from agents import (
    ProjectManagerAgent,
    SoftwareEngineerAgent,
    UIUXEngineerAgent,
    DatabaseAdminAgent,
    SecurityReviewerAgent,
    QATesterAgent,
    TestingAgent
)
from .memory import MemoryManager
from .project import ProjectManager, ProjectStatus
from .playwright_utils import PlaywrightManager


class TaskFailureAction(Enum):
    """Actions that can be taken when a task fails."""
    RETRY = "retry"
    SKIP = "skip"
    MODIFY_TASK = "modify"
    REMOVE_TASK = "remove"
    STOP_WORK = "stop"


class Orchestrator:
    """
    The Orchestrator coordinates all agents and manages the flow of work.
    Uses Claude Code CLI for agent execution (your existing subscription).

    It handles:
    - Agent instantiation and configuration
    - Task routing between agents
    - Human input requests
    - Activity logging
    - Self-healing (retry logic)
    """

    def __init__(
        self,
        project_path: str,
        config: Dict[str, Any],
        activity_callback: Optional[Callable] = None,
        human_input_callback: Optional[Callable] = None,
        message_callback: Optional[Callable] = None
    ):
        self.project_path = project_path
        self.config = config
        self.activity_callback = activity_callback
        self.human_input_callback = human_input_callback
        self.message_callback = message_callback  # For sending work status updates
        self.activity_log: List[Dict[str, Any]] = []
        self.memory = MemoryManager(project_path)

        # Project status management
        base_path = os.path.dirname(project_path)
        self.project_manager_core = ProjectManager(os.path.dirname(base_path))
        self.project_name = os.path.basename(project_path)

        # Playwright for QA testing
        self.playwright_manager = PlaywrightManager(config)
        self.playwright_available = self.playwright_manager.is_available()

        # Pending human input requests
        self.pending_human_input: Optional[Dict[str, Any]] = None
        self.human_input_event = asyncio.Event()
        self.todo_lock = asyncio.Lock()

        # Work state
        self.is_working = False
        self.pause_requested = False
        self.total_failures = 0  # Track total failures for critical error detection
        self.active_tasks = set()
        self.work_task: Optional[asyncio.Task] = None

        # User escalation state
        self.pending_user_decision = None
        self.user_decision_event = asyncio.Event()
        self.user_decision_response = None

        # Parallel execution settings
        exec_config = config.get('execution', {})
        self.max_concurrent = exec_config.get('max_concurrent_agents', 3)
        self.task_timeout = exec_config.get('task_timeout_seconds', 600)
        self.simple_task_timeout = exec_config.get('simple_task_timeout_seconds', 300)
        self.max_task_retries = exec_config.get('max_task_retries', 3)
        self.allow_cross_section_parallel = exec_config.get('allow_cross_section_parallel', True)
        self.enable_task_batching = exec_config.get('enable_task_batching', True)
        self.task_batch_size = exec_config.get('task_batch_size', 2)
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        default_strategy = config.get("defaults", {}).get("testing_strategy", "critical_paths")
        project_strategy = self.project_manager_core.get_testing_strategy(self.project_name)
        self.testing_strategy = project_strategy or default_strategy
        self.last_test_result: Optional[Dict[str, Any]] = None
        default_gates = config.get("quality_gates", {})
        project_gates = self.project_manager_core.get_quality_gates(self.project_name)
        merged_gates = default_gates.copy()
        merged_gates.update(project_gates or {})
        self.quality_gates = merged_gates

        # Initialize agents
        self._init_agents()

    def _init_agents(self):
        """Initialize all agents with model preferences from config."""
        agent_configs = self.config.get('agents', {})

        self.agents = {
            "project_manager": ProjectManagerAgent(
                activity_callback=self._log_activity,
                model_preference=agent_configs.get('project_manager', {}).get('model', 'opus')
            ),
            "software_engineer": SoftwareEngineerAgent(
                activity_callback=self._log_activity,
                model_preference=agent_configs.get('software_engineer', {}).get('model', 'auto')
            ),
            "ui_ux_engineer": UIUXEngineerAgent(
                activity_callback=self._log_activity,
                model_preference=agent_configs.get('ui_ux_engineer', {}).get('model', 'auto')
            ),
            "database_admin": DatabaseAdminAgent(
                activity_callback=self._log_activity,
                model_preference=agent_configs.get('database_admin', {}).get('model', 'auto')
            ),
            "security_reviewer": SecurityReviewerAgent(
                activity_callback=self._log_activity,
                model_preference=agent_configs.get('security_reviewer', {}).get('model', 'opus')
            ),
            "testing_agent": TestingAgent(
                activity_callback=self._log_activity,
                model_preference=agent_configs.get('testing_agent', {}).get('model', 'auto')
            ),
            "qa_tester": QATesterAgent(
                activity_callback=self._log_activity,
                model_preference=agent_configs.get('qa_tester', {}).get('model', 'auto'),
                playwright_available=self.playwright_available
            )
        }

        # Wire debug streaming if enabled
        debug_enabled = self.config.get('debug', {}).get('enabled', False)
        if debug_enabled and self.message_callback:
            for agent_name, agent in self.agents.items():
                agent.stream_callback = self._make_stream_callback(agent_name)

    def _make_stream_callback(self, agent_name: str):
        """Create a stream callback for debug mode that broadcasts lines via WebSocket."""
        async def stream_cb(name: str, line: str):
            if self.message_callback:
                await self.message_callback({
                    "type": "debug_output",
                    "agent": name,
                    "line": line,
                    "timestamp": datetime.now().isoformat()
                })
        return stream_cb

    def set_debug_mode(self, enabled: bool):
        """Enable or disable debug streaming on all agents at runtime."""
        for agent_name, agent in self.agents.items():
            if enabled and self.message_callback:
                agent.stream_callback = self._make_stream_callback(agent_name)
            else:
                agent.stream_callback = None

    def _log_activity(self, activity: Dict[str, Any]):
        """Log an activity and notify listeners."""
        self.activity_log.append(activity)
        if self.activity_callback:
            self.activity_callback(activity)

    async def _log_error(self, error_type: str, task: str, error_details: str, agent: str = "unknown"):
        """Log an error to error_log.md for later analysis."""
        error_log_path = os.path.join(self.project_path, "error_log.md")

        timestamp = datetime.now().isoformat()
        error_entry = f"""
## Error: {error_type}
- **Timestamp:** {timestamp}
- **Agent:** {agent}
- **Task:** {task[:200]}
- **Details:** {error_details[:500]}
---
"""

        try:
            # Append to error log (create if doesn't exist)
            if os.path.exists(error_log_path):
                async with aiofiles.open(error_log_path, 'a', encoding='utf-8') as f:
                    await f.write(error_entry)
            else:
                async with aiofiles.open(error_log_path, 'w', encoding='utf-8') as f:
                    await f.write("# Error Log\n\nThis file contains errors encountered during project execution for analysis and improvement.\n\n")
                    await f.write(error_entry)
        except Exception as e:
            # Don't fail if we can't write the error log
            self._log_activity({
                "timestamp": timestamp,
                "agent": "orchestrator",
                "action": "Failed to write error log",
                "details": str(e)[:100]
            })

    async def _escalate_to_user(self, task: str, error: str, agent: str) -> TaskFailureAction:
        """Escalate a task failure to the user for decision."""
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Escalating to user",
            "details": f"Task failed: {task[:50]}..."
        })

        # Send message asking user what to do
        escalation_message = f"""A task has failed and needs your input.

**Failed Task:** {task[:100]}{'...' if len(task) > 100 else ''}

**Error:** {error[:200]}{'...' if len(error) > 200 else ''}

**What would you like to do?**
1. **retry** - Try the task again
2. **skip** - Skip this task and continue with others
3. **modify** - Let me suggest a simpler version of this task
4. **remove** - Remove this task from TODO.md
5. **stop** - Stop all work

Please reply with one of: retry, skip, modify, remove, or stop"""

        await self._send_message(
            "user_escalation",
            escalation_message,
            task=task,
            error=error,
            agent=agent
        )

        # Wait for user response
        self.pending_user_decision = {"task": task, "error": error}
        self.user_decision_event.clear()

        try:
            # Wait up to 5 minutes for user response, then default to skip
            await asyncio.wait_for(self.user_decision_event.wait(), timeout=300)
            response = self.user_decision_response
        except asyncio.TimeoutError:
            self._log_activity({
                "timestamp": datetime.now().isoformat(),
                "agent": "orchestrator",
                "action": "Escalation timeout",
                "details": "No user response after 5 minutes, defaulting to skip"
            })
            response = "skip"

        self.pending_user_decision = None
        self.user_decision_response = None

        # Parse response
        response_lower = response.lower().strip()
        if "retry" in response_lower:
            return TaskFailureAction.RETRY
        elif "modify" in response_lower:
            return TaskFailureAction.MODIFY_TASK
        elif "remove" in response_lower:
            return TaskFailureAction.REMOVE_TASK
        elif "stop" in response_lower:
            return TaskFailureAction.STOP_WORK
        else:
            return TaskFailureAction.SKIP

    def receive_user_decision(self, decision: str):
        """Receive a decision from the user for a pending escalation."""
        if self.pending_user_decision:
            self.user_decision_response = decision
            self.user_decision_event.set()

    async def _modify_task_in_todo(self, old_task: str, new_task: str):
        """Modify a task in TODO.md."""
        todo_path = os.path.join(self.project_path, "TODO.md")
        if not os.path.exists(todo_path):
            return

        async with self.todo_lock:
            async with aiofiles.open(todo_path, 'r', encoding='utf-8') as f:
                content = await f.read()

            old_line = f"- [ ] {old_task}"
            new_line = f"- [ ] {new_task}"
            content = content.replace(old_line, new_line)

            async with aiofiles.open(todo_path, 'w', encoding='utf-8') as f:
                await f.write(content)

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Task modified",
            "details": f"Changed to: {new_task[:100]}"
        })

    async def _remove_task_from_todo(self, task_text: str):
        """Remove a task from TODO.md."""
        todo_path = os.path.join(self.project_path, "TODO.md")
        if not os.path.exists(todo_path):
            return

        async with self.todo_lock:
            async with aiofiles.open(todo_path, 'r', encoding='utf-8') as f:
                content = await f.read()

            # Remove the task line
            old_line = f"- [ ] {task_text}"
            content = content.replace(old_line + "\n", "")
            content = content.replace(old_line, "")  # In case it's the last line

            async with aiofiles.open(todo_path, 'w', encoding='utf-8') as f:
                await f.write(content)

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Task removed",
            "details": task_text[:100]
        })

    async def _estimate_task_complexity(self, task: str) -> str:
        """
        Estimate task complexity: small, medium, or large.
        Uses quick heuristics only (no LLM call) for speed.
        """
        task_lower = task.lower()

        # Quick heuristics for obvious cases
        small_indicators = ['fix typo', 'update text', 'change color', 'rename', 'add comment', 'remove unused']
        large_indicators = ['implement', 'create full', 'build complete', 'design and implement',
                          'refactor entire', 'migrate', 'integrate', 'authentication system',
                          'database schema', 'api endpoints', 'full crud']

        # Check for small tasks
        if any(ind in task_lower for ind in small_indicators) or len(task) < 50:
            return "small"

        # Check for large tasks
        if any(ind in task_lower for ind in large_indicators) or len(task) > 200:
            return "large"

        # For medium-complexity or uncertain tasks, ask PM for quick estimate
        return "medium"  # Default to medium for uncertain cases

    async def _split_large_task(self, task: str) -> List[str]:
        """Split a large task into smaller subtasks."""
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Splitting large task",
            "details": task[:100]
        })
        # Heuristic split for speed: split on sentence-like separators or "and then"
        separators = ["\n", ";", " and then ", " then ", ". "]
        parts = [task]
        for sep in separators:
            if sep in task:
                parts = [p.strip() for p in task.split(sep) if p.strip()]
                break

        # Keep reasonable subtasks only if we got multiple meaningful parts
        if len(parts) >= 2:
            subtasks = [p if p.endswith('.') else p for p in parts]
            return subtasks[:4]

        # Fallback: return original task if splitting is not obvious
        return [task]

    async def _replace_task_with_subtasks(self, original_task: str, subtasks: List[str]):
        """Replace a task in TODO.md with its subtasks."""
        todo_path = os.path.join(self.project_path, "TODO.md")
        if not os.path.exists(todo_path):
            return

        async with self.todo_lock:
            async with aiofiles.open(todo_path, 'r', encoding='utf-8') as f:
                content = await f.read()

            # Build replacement text
            old_line = f"- [ ] {original_task}"
            new_lines = "\n".join([f"- [ ] {st}" for st in subtasks])

            content = content.replace(old_line, new_lines)

            async with aiofiles.open(todo_path, 'w', encoding='utf-8') as f:
                await f.write(content)

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Task split into subtasks",
            "details": f"Created {len(subtasks)} subtasks"
        })

    async def _suggest_simpler_task(self, original_task: str, error: str) -> str:
        """Create a simpler version of a failed task using local heuristics.

        Avoids burning a full CLI round-trip (and its tokens) just to rephrase a string.
        Strips the task to its core intent and adds a focus hint with the error context.
        """
        # Take the first sentence or first 120 chars as the core intent
        core = original_task.split('.')[0].split(';')[0].strip()
        if len(core) > 120:
            core = core[:120].rsplit(' ', 1)[0]

        # Build a brief error hint so the retry knows what to avoid
        error_brief = error.split('\n')[0][:100].strip()

        return f"{core}. (Previous attempt failed: {error_brief}. Keep the implementation minimal.)"

    async def route_message(
        self,
        from_agent: str,
        to_agent: str,
        message: str
    ) -> str:
        """Route a message from one agent to another."""
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": from_agent,
            "action": f"Message to {to_agent}",
            "details": message[:100]
        })

        if to_agent not in self.agents:
            return f"Error: Unknown agent {to_agent}"

        target_agent = self.agents[to_agent]

        # Get minimal context for the task
        context = self.memory.get_context_for_task(message)

        result = await target_agent.process_task(
            task=message,
            project_path=self.project_path,
            context=context,
            orchestrator=self,
            config=self.config
        )

        return result.get("result", "No response")

    async def request_human_input(self, agent: str, question: str) -> str:
        """Request input from the human user."""
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "action": "Requesting human input",
            "details": question
        })

        if self.human_input_callback:
            # Set up pending request
            self.pending_human_input = {
                "agent": agent,
                "question": question,
                "timestamp": datetime.now().isoformat()
            }
            self.human_input_event.clear()

            # Notify UI
            self.human_input_callback(self.pending_human_input)

            # Wait for response
            await self.human_input_event.wait()

            response = self.pending_human_input.get("response", "")
            self.pending_human_input = None

            return response

        return "No human input handler configured"

    def provide_human_input(self, response: str):
        """Provide a response to a pending human input request."""
        if self.pending_human_input:
            self.pending_human_input["response"] = response
            self.human_input_event.set()

    async def assign_task(
        self,
        agent_name: str,
        task: str,
        context: str = "",
        priority: str = "medium"
    ) -> Dict[str, Any]:
        """Assign a task to a specific agent with timeout and retry handling."""
        if agent_name not in self.agents:
            return {"status": "error", "result": f"Unknown agent: {agent_name}"}

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": f"Assigning task to {agent_name}",
            "details": f"[{priority}] {task[:100]}"
        })

        agent = self.agents[agent_name]

        # Get relevant context from memory
        if not context:
            context = self.memory.get_context_for_task(task)

        # Execute with retry logic.
        # Timeouts are NOT retried — the same prompt will almost certainly
        # timeout again, burning tokens for nothing.  Let the higher-level
        # _execute_tasks escalation (modify/skip/user prompt) handle it.
        # Exceptions ARE retried with an error hint appended so the agent
        # knows what went wrong on the previous attempt.
        retries = 0
        last_error: Optional[str] = None

        while retries < self.max_task_retries:
            # On retry, append the previous error so the agent can adapt
            effective_task = task
            if last_error:
                error_brief = last_error.split('\n')[0][:150].strip()
                effective_task = f"{task}\n\n(Previous attempt failed: {error_brief}. Adjust your approach.)"

            try:
                # Notify UI that agent is starting
                await self._notify_agent_start(agent_name)

                # Use semaphore to limit concurrent agents
                async with self.semaphore:
                    result = await agent.process_task(
                        task=effective_task,
                        project_path=self.project_path,
                        context=context,
                        orchestrator=self,
                        config=self.config,
                        timeout=self.task_timeout
                    )

                # Notify UI that agent finished
                await self._notify_agent_complete(agent_name)

                if result["status"] == "complete":
                    # Update memory with result
                    self.memory.record_action(agent_name, task, result["result"])
                    self.total_failures = 0  # Reset on success
                    return result

                if result["status"] == "timeout":
                    # Don't retry timeouts — same prompt will likely timeout again
                    self.total_failures += 1
                    self._log_activity({
                        "timestamp": datetime.now().isoformat(),
                        "agent": "orchestrator",
                        "action": "Timeout (no retry)",
                        "details": f"Task timed out after {self.task_timeout}s — skipping retry to save tokens"
                    })
                    await self._log_error(
                        error_type="timeout",
                        task=task,
                        error_details=f"Task timed out after {self.task_timeout}s (not retried)",
                        agent=agent_name
                    )
                    return {
                        "status": "timeout",
                        "result": f"Task timed out after {self.task_timeout}s"
                    }

            except Exception as e:
                await self._notify_agent_complete(agent_name)
                self.total_failures += 1
                error_msg = str(e).encode('ascii', errors='replace').decode('ascii')
                last_error = error_msg
                self._log_activity({
                    "timestamp": datetime.now().isoformat(),
                    "agent": "orchestrator",
                    "action": f"Task error ({retries + 1}/{self.max_task_retries})",
                    "details": error_msg[:200]
                })
                await self._log_error(
                    error_type="exception",
                    task=task,
                    error_details=error_msg,
                    agent=agent_name
                )

            retries += 1

            # Check for critical failure threshold (too many total failures)
            if self.total_failures >= self.max_task_retries * 2:
                await self._log_error(
                    error_type="critical",
                    task=task,
                    error_details=f"Critical failure threshold reached ({self.total_failures} failures). Work stopped.",
                    agent=agent_name
                )
                await self._send_message(
                    "critical_error",
                    f"Too many failures ({self.total_failures}). Stopping work. Please check the logs and error_log.md."
                )
                self.is_working = False
                return {"status": "critical_error", "result": "Too many failures"}

        # Return error after max retries
        return {
            "status": "error",
            "result": f"Task failed after {self.max_task_retries} retries"
        }

    def _reset_all_sessions(self):
        """Reset CLI session IDs on all agents so they start fresh."""
        for agent in self.agents.values():
            agent.reset_session()

    async def start_project_kickoff(self, initial_request: str) -> Dict[str, Any]:
        """Start a new project with the PM asking kickoff questions."""
        self._reset_all_sessions()
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Starting project kickoff",
            "details": initial_request[:100]
        })

        pm = self.agents["project_manager"]

        kickoff_task = f"""A user wants to start a new project. Their initial request is:

"{initial_request}"

Please begin the project kickoff by asking questions to understand their requirements.
Ask ONE question at a time. You will receive their answers and can ask follow-up questions.
After gathering enough information (15-20 questions), create the SPEC.md and TODO.md files.
If the project involves Python, make sure the TODO list includes, near the top, a task to create a project-local .venv with uv, activate it, and install required libraries there; ensure tests/run commands use the project's .venv."""

        result = await pm.process_task(
            task=kickoff_task,
            project_path=self.project_path,
            context="",
            orchestrator=self,
            config=self.config
        )

        return result

    async def start_feature_request(self, feature_request: str) -> Dict[str, Any]:
        """Handle a new feature request on an existing project."""
        self._reset_all_sessions()
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Starting feature request",
            "details": feature_request[:100]
        })

        pm = self.agents["project_manager"]

        # Load existing spec if available
        spec_path = os.path.join(self.project_path, "SPEC.md")
        existing_spec = ""
        if os.path.exists(spec_path):
            with open(spec_path, 'r') as f:
                existing_spec = f.read()

        feature_task = f"""A user wants to add a new feature to an existing project.

Existing project spec:
{existing_spec}

Feature request:
"{feature_request}"

Please ask questions to understand this feature (around 10 questions).
Ask ONE question at a time. After gathering enough information, update SPEC.md and TODO.md.
If the project involves Python, ensure the TODO list includes, near the top, a task to create a project-local .venv with uv, activate it, and install required libraries there; ensure tests/run commands use the project's .venv."""

        result = await pm.process_task(
            task=feature_task,
            project_path=self.project_path,
            context=self.memory.get_project_summary(),
            orchestrator=self,
            config=self.config
        )

        return result

    def request_pause(self):
        """Request a pause after the current task completes."""
        self.pause_requested = True
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Pause requested",
            "details": "Will stop after current task completes"
        })

    async def force_stop(self, reason: str = "Force stop requested"):
        """Force stop all current activity immediately."""
        self.is_working = False
        self.pause_requested = True

        # Unblock any pending user decision
        self.user_decision_response = "stop"
        self.user_decision_event.set()

        # Cancel active tasks
        for task in list(self.active_tasks):
            if not task.done():
                task.cancel()
        self.active_tasks.clear()

        # Cancel the work task itself if running
        if self.work_task and not self.work_task.done():
            self.work_task.cancel()

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Force stop",
            "details": reason
        })
        await self._send_message("work_stopped", "Work force-stopped.")

    async def _send_message(self, msg_type: str, message: str, **kwargs):
        """Send a message to the frontend."""
        if self.message_callback:
            msg = {
                "type": msg_type,
                "message": message,
                "timestamp": datetime.now().isoformat()
            }
            msg.update(kwargs)
            await self.message_callback(msg)

    async def _notify_agent_start(self, agent_name: str):
        """Notify UI that an agent started working."""
        await self._send_message("agent_start", f"{agent_name} started", agent=agent_name)

    async def _notify_agent_complete(self, agent_name: str):
        """Notify UI that an agent finished working."""
        await self._send_message("agent_complete", f"{agent_name} finished", agent=agent_name)

    # Regex for parsing task lines with optional {ID} and [depends: ...] tags
    _TASK_PATTERN = re.compile(
        r'^- \[(?P<check>[ xX])\]\s*'          # checkbox
        r'(?:\{(?P<id>\d+)\}\s*)?'              # optional {ID}
        r'(?P<text>.*?)'                        # task text (non-greedy)
        r'(?:\s*\[depends:\s*(?P<deps>[\d,\s]+)\])?' # optional [depends: ...]
        r'\s*$'
    )

    def _parse_todo_tasks(self) -> List[Dict[str, Any]]:
        """Parse TODO.md and return list of tasks with their status and dependencies."""
        todo_path = os.path.join(self.project_path, "TODO.md")
        if not os.path.exists(todo_path):
            return []

        with open(todo_path, 'r', encoding='utf-8') as f:
            content = f.read()

        tasks = []
        current_section = "General"

        for line in content.split('\n'):
            stripped = line.strip()

            # Detect section headers
            if stripped.startswith('## '):
                current_section = stripped[3:].strip()
                continue

            m = self._TASK_PATTERN.match(stripped)
            if m:
                check = m.group('check')
                task_id_str = m.group('id')
                text = m.group('text').strip()
                deps_str = m.group('deps')

                task_id = int(task_id_str) if task_id_str else None
                depends_on = []
                if deps_str:
                    depends_on = [int(d.strip()) for d in deps_str.split(',') if d.strip().isdigit()]

                # Build the full raw text (with {ID} and [depends:]) for matching during completion
                raw_text = text
                if task_id is not None:
                    raw_text = f"{{{task_id}}} {text}"
                if depends_on:
                    raw_text += f" [depends: {', '.join(str(d) for d in depends_on)}]"

                tasks.append({
                    "text": raw_text,
                    "display_text": text,  # clean text without ID/deps for agent prompt
                    "completed": check in ('x', 'X'),
                    "section": current_section,
                    "id": task_id,
                    "depends_on": depends_on
                })
            else:
                # Fallback: parse plain checkbox lines without ID/deps (legacy format)
                if stripped.startswith('- [ ] '):
                    tasks.append({
                        "text": stripped[6:].strip(),
                        "display_text": stripped[6:].strip(),
                        "completed": False,
                        "section": current_section,
                        "id": None,
                        "depends_on": []
                    })
                elif stripped.startswith('- [x] ') or stripped.startswith('- [X] '):
                    tasks.append({
                        "text": stripped[6:].strip(),
                        "display_text": stripped[6:].strip(),
                        "completed": True,
                        "section": current_section,
                        "id": None,
                        "depends_on": []
                    })

        return tasks

    def _get_next_task(self) -> Optional[Dict[str, Any]]:
        """Get the next uncompleted, dependency-ready task from TODO.md."""
        tasks = self._parse_todo_tasks()
        completed_ids = self._get_completed_task_ids(tasks)
        for task in tasks:
            if not task["completed"] and self._is_task_ready(task, completed_ids):
                return task
        return None

    def _get_completed_task_ids(self, tasks: List[Dict[str, Any]]) -> Set[int]:
        """Get the set of completed task IDs."""
        return {t["id"] for t in tasks if t["completed"] and t["id"] is not None}

    def _is_task_ready(self, task: Dict[str, Any], completed_ids: Set[int]) -> bool:
        """Check if a task's dependencies are all satisfied."""
        if not task["depends_on"]:
            return True
        return all(dep_id in completed_ids for dep_id in task["depends_on"])

    def _get_parallel_tasks(self, max_tasks: int = None) -> List[Dict[str, Any]]:
        """
        Get a batch of tasks that can run in parallel.
        Only returns tasks whose dependencies are fully satisfied.
        Prefers tasks from the same section, but allows cross-section batching.
        """
        if max_tasks is None:
            max_tasks = self.max_concurrent

        tasks = self._parse_todo_tasks()
        completed_ids = self._get_completed_task_ids(tasks)
        uncompleted = [t for t in tasks if not t["completed"]]

        # Filter to only dependency-ready tasks
        ready = [t for t in uncompleted if self._is_task_ready(t, completed_ids)]

        if not ready:
            return []

        # Start with the first section for locality
        first_section = ready[0]["section"]
        batch: List[Dict[str, Any]] = []

        # Add tasks from the first section
        for t in ready:
            if t["section"] == first_section:
                batch.append(t)
                if len(batch) >= max_tasks:
                    return batch

        if not self.allow_cross_section_parallel:
            return batch

        # Fill remaining slots with tasks from other sections, preserving order
        for t in ready:
            if t["section"] != first_section:
                batch.append(t)
                if len(batch) >= max_tasks:
                    break

        return batch

    def _is_small_task(self, task_text: str) -> bool:
        """Heuristic to decide if a task is small enough to batch."""
        text = task_text.lower().strip()
        if len(text) > 150:
            return False
        large_indicators = [
            "refactor", "migrate", "architecture",
            "authentication", "authorization", "database schema", "full crud",
            "design and implement", "build complete"
        ]
        return not any(ind in text for ind in large_indicators)

    def _batch_tasks_by_section(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Batch small tasks in the same section into a single work item."""
        if not self.enable_task_batching or self.task_batch_size <= 1:
            return tasks

        batched: List[Dict[str, Any]] = []
        i = 0
        while i < len(tasks):
            current = tasks[i]
            section = current["section"]
            group = [current]
            j = i + 1
            while j < len(tasks) and len(group) < self.task_batch_size:
                candidate = tasks[j]
                if candidate["section"] != section:
                    break
                if not self._is_small_task(candidate.get("display_text", candidate["text"])) or not self._is_small_task(current.get("display_text", current["text"])):
                    break
                group.append(candidate)
                j += 1

            if len(group) > 1:
                combined_display = "\n".join([f"- {t.get('display_text', t['text'])}" for t in group])
                batched.append({
                    "text": f"BATCHED TASKS:\n{combined_display}",
                    "display_text": f"BATCHED TASKS:\n{combined_display}",
                    "completed": False,
                    "section": section,
                    "id": None,
                    "depends_on": [],
                    "batch": group
                })
                i = j
            else:
                batched.append(current)
                i += 1

        return batched

    async def _execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single task and return the result."""
        task_text = task.get("display_text", task["text"])
        start_time = datetime.now()

        # Log task start with timestamp
        self._log_activity({
            "timestamp": start_time.isoformat(),
            "agent": "orchestrator",
            "action": "Task started",
            "details": f"[{start_time.strftime('%H:%M:%S')}] {task_text[:80]}..."
        })

        # Estimate complexity (skip for batched tasks)
        complexity = "medium"
        if "batch" not in task:
            complexity = await self._estimate_task_complexity(task_text)

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": f"Task complexity: {complexity.upper()}",
            "details": task_text[:50]
        })

        # If task is large, split it into subtasks
        if complexity == "large" and "batch" not in task:
            await self._send_message("info", f"Large task detected, splitting: {task_text[:40]}...")

            subtasks = await self._split_large_task(task_text)

            if len(subtasks) > 1:
                await self._replace_task_with_subtasks(task_text, subtasks)
                await self._send_message("info", f"Split into {len(subtasks)} subtasks")

                # Return special status to indicate task was split (not executed)
                return {
                    "task": task,
                    "result": {"status": "split", "result": f"Split into {len(subtasks)} subtasks"},
                    "agent": "orchestrator"
                }

        # Determine agent and execute
        agent_name = self._determine_agent_for_task(task_text)

        mgmt_port = self.config.get("server_port", 8080)
        port_warning = f"\n\nIMPORTANT: Port {mgmt_port} is reserved for the management interface. If you need to start a web server or use Playwright, NEVER use port {mgmt_port}."
        task_context = f"Section: {task['section']}\n\n" + self.memory.get_context_for_task(task_text, section=task['section']) + port_warning

        result = await self.assign_task(
            agent_name=agent_name,
            task=task_text,
            context=task_context
        )

        # Log task completion with duration
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        duration_str = f"{int(duration // 60)}m {int(duration % 60)}s" if duration >= 60 else f"{int(duration)}s"

        self._log_activity({
            "timestamp": end_time.isoformat(),
            "agent": agent_name,
            "action": f"Task finished ({duration_str})",
            "details": f"Status: {result['status']}"
        })

        # Mark tasks complete immediately on success to avoid lag/duplication
        if result["status"] == "complete":
            if "batch" in task:
                for subtask in task["batch"]:
                    await self._mark_task_complete(subtask["text"])
            else:
                # Use raw text (with {ID} and [depends:]) for accurate matching
                await self._mark_task_complete(task.get("text", task_text))

        return {"task": task, "result": result, "agent": agent_name}

    async def start_work(self) -> Dict[str, Any]:
        """Start working through TODO tasks with parallel execution and self-healing."""
        if self.is_working:
            return {"status": "error", "result": "Work already in progress"}

        self.is_working = True
        self.pause_requested = False
        self.total_failures = 0
        skipped_tasks = set()

        # Set status to WIP
        await self._set_project_status(ProjectStatus.WIP, "Work started")

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Starting work",
            "details": f"Parallel execution enabled (max {self.max_concurrent} agents)"
        })

        await self._send_message("work_started", "Work started")

        try:
            while self.is_working and not self.pause_requested:
                # Get batch of parallel tasks
                tasks = self._get_parallel_tasks()

                # Filter out skipped tasks
                tasks = [t for t in tasks if t["text"] not in skipped_tasks]

                if not tasks:
                    # Check if there are any remaining uncompleted tasks
                    remaining = self._get_next_task()
                    if remaining and remaining["text"] not in skipped_tasks:
                        tasks = [remaining]
                    else:
                        self._log_activity({
                            "timestamp": datetime.now().isoformat(),
                            "agent": "orchestrator",
                            "action": "All tasks complete",
                            "details": f"Completed. Skipped {len(skipped_tasks)} problematic tasks."
                        })

                        # Optional Testing phase before security
                        testing_issues = []
                        if self._should_run_testing_phase_now():
                            await self._set_project_status(
                                ProjectStatus.TESTING,
                                "All tasks complete, starting testing"
                            )

                            testing_result = await self._run_testing_phase()
                            if testing_result:
                                testing_issues = testing_result.get("issues", []) or []
                        else:
                            # Smoke testing (run existing tests without testing agent)
                            strategy = self._normalize_testing_strategy()
                            if (self.quality_gates.get("run_tests", True)
                                    and strategy in {"smoke", "smoke_tests", "smoke_test"}
                                    and self._has_code_changes_since_last_review()):
                                test_result = await self._run_tests()
                                self.last_test_result = test_result
                                if test_result.get("status") in {"failed", "error", "timeout"}:
                                    testing_issues.append({
                                        "title": "[BLOCKING] Smoke tests failed",
                                        "description": (test_result.get("summary", "") or "pytest failed").strip()[:400]
                                    })

                        if testing_issues:
                            issues_added = await self._handle_review_issues(testing_issues, "Testing")
                            if issues_added:
                                continue  # Continue working on new issues

                        # Run Security Review phase (if enabled)
                        if self.quality_gates.get("run_security_review", True):
                            await self._set_project_status(
                                ProjectStatus.SECURITY_REVIEW,
                                "All tasks complete, starting security review"
                            )

                            security_result = await self._run_final_security_review()

                            # Check for security issues
                            security_issues = []
                            if security_result and security_result.get("status") == "complete":
                                result_text = security_result.get("result", "")
                                security_issues = self._parse_review_issues(result_text)

                            if security_issues:
                                # Issues found, add to TODO and go back to WIP
                                issues_added = await self._handle_review_issues(security_issues, "Security")
                                if issues_added:
                                    continue  # Continue working on new issues
                            else:
                                self._save_quality_marker()

                        # Security passed (or skipped), run QA Review phase
                        qa_result = await self._run_qa_review()
                        if qa_result and qa_result.get("status") != "skipped":
                            await self._set_project_status(
                                ProjectStatus.QA,
                                "Security review passed, starting QA"
                            )

                        # Check for blocking/major QA issues
                        qa_issues = []
                        if qa_result and qa_result.get("status") == "complete":
                            result_text = qa_result.get("result", "")

                            # Add non-issue notes to QA notes file
                            if "qa passed" in result_text.lower():
                                await self._add_qa_notes(
                                    f"QA Review completed successfully.\n\n{result_text[:1000]}",
                                    "QA Review Notes"
                                )
                                self._save_quality_marker()
                            else:
                                qa_issues = self._parse_review_issues(result_text)

                        if qa_issues:
                            # Issues found, add to TODO and go back to WIP
                            issues_added = await self._handle_review_issues(qa_issues, "QA")
                            if issues_added:
                                continue  # Continue working on new issues

                        # QA passed or skipped - transition to UAT (User Acceptance Testing)
                        await self._set_project_status(
                            ProjectStatus.UAT,
                            "Reviews complete - ready for user acceptance testing"
                        )

                        # Notify UI that UAT is ready
                        await self._send_message(
                            "uat_ready",
                            "All automated checks passed! Ready for User Acceptance Testing. Click 'Start UAT' to begin your review."
                        )

                        # Work pauses here - UAT is a user-driven conversation
                        self._log_activity({
                            "timestamp": datetime.now().isoformat(),
                            "agent": "orchestrator",
                            "action": "Awaiting UAT",
                            "details": "Project ready for user acceptance testing"
                        })
                        break

                self._log_activity({
                    "timestamp": datetime.now().isoformat(),
                    "agent": "orchestrator",
                    "action": f"Running {len(tasks)} task(s) in parallel",
                    "details": ", ".join([t["text"][:30] + "..." for t in tasks])
                })

                # Batch small tasks by section to reduce CLI invocations
                tasks = self._batch_tasks_by_section(tasks)

                # Execute tasks in parallel
                task_futures = [asyncio.create_task(self._execute_task(task)) for task in tasks]
                self.active_tasks.update(task_futures)
                results = await asyncio.gather(*task_futures, return_exceptions=True)
                for t in task_futures:
                    self.active_tasks.discard(t)

                # Process results
                for res in results:
                    if isinstance(res, Exception):
                        error_msg = str(res).encode('ascii', errors='replace').decode('ascii')
                        self._log_activity({
                            "timestamp": datetime.now().isoformat(),
                            "agent": "orchestrator",
                            "action": "Task exception",
                            "details": error_msg[:200]
                        })
                        continue

                    task = res["task"]
                    result = res["result"]

                    if result["status"] == "complete":
                        # Marked inside _execute_task to reduce UI lag
                        pass
                    elif result["status"] == "split":
                        # Task was split into subtasks, will be picked up on next iteration
                        self._log_activity({
                            "timestamp": datetime.now().isoformat(),
                            "agent": "orchestrator",
                            "action": "Task split",
                            "details": "Subtasks added to TODO.md"
                        })
                    elif result["status"] == "critical_error":
                        # Critical error already sent to UI, stop work
                        self.is_working = False
                        break
                    elif result["status"] in ("error", "timeout"):
                        # Log the error
                        error_msg = result.get("result", "Unknown error")
                        await self._log_error(
                            error_type=result["status"],
                            task=task["text"],
                            error_details=error_msg,
                            agent=res.get("agent", "unknown")
                        )

                        # Escalate to user for decision
                        action = await self._escalate_to_user(
                            task=task["text"],
                            error=error_msg,
                            agent=res.get("agent", "unknown")
                        )

                        if action == TaskFailureAction.RETRY:
                            # Don't add to skipped, will retry on next loop
                            self._log_activity({
                                "timestamp": datetime.now().isoformat(),
                                "agent": "orchestrator",
                                "action": "Retrying task",
                                "details": task["text"][:100]
                            })
                        elif action == TaskFailureAction.SKIP:
                            skipped_tasks.add(task["text"])
                            await self._send_message("info", f"Skipped: {task['text'][:50]}...")
                        elif action == TaskFailureAction.MODIFY_TASK:
                            # Get a simpler version of the task
                            new_task = await self._suggest_simpler_task(task["text"], error_msg)
                            await self._modify_task_in_todo(task["text"], new_task)
                            await self._send_message("info", f"Task modified to: {new_task[:50]}...")
                        elif action == TaskFailureAction.REMOVE_TASK:
                            await self._remove_task_from_todo(task["text"])
                            await self._send_message("info", f"Removed task: {task['text'][:50]}...")
                        elif action == TaskFailureAction.STOP_WORK:
                            await self._send_message("work_paused", "Work stopped by user request")
                            self.is_working = False
                            break

                # Check for pause request
                if self.pause_requested:
                    self._log_activity({
                        "timestamp": datetime.now().isoformat(),
                        "agent": "orchestrator",
                        "action": "Work paused",
                        "details": "Pause requested by user"
                    })
                    await self._send_message("work_paused", "Work paused. Click 'Start Work' to resume.")
                    break

                # Check for too many total failures
                if self.total_failures >= self.max_task_retries * 3:
                    await self._send_message(
                        "critical_error",
                        f"Too many failures ({self.total_failures}). Work stopped."
                    )
                    break

        except asyncio.CancelledError:
            self._log_activity({
                "timestamp": datetime.now().isoformat(),
                "agent": "orchestrator",
                "action": "Work force-stopped",
                "details": "Cancelled by user"
            })
            await self._send_message("work_stopped", "Work force-stopped.")
            return {"status": "stopped", "result": "Work force-stopped"}
        except Exception as e:
            # Critical error - send to UI
            error_msg = str(e).encode('ascii', errors='replace').decode('ascii')
            self._log_activity({
                "timestamp": datetime.now().isoformat(),
                "agent": "orchestrator",
                "action": "Critical error",
                "details": error_msg
            })
            await self._send_message("critical_error", f"Critical error: {error_msg}")

        finally:
            self.is_working = False
            self.pause_requested = False

        return {"status": "complete", "result": "Work session ended"}

    def _determine_agent_for_task(self, task_text: str) -> str:
        """Determine which agent should handle a task based on keywords."""
        task_lower = task_text.lower()

        # QA/Testing related
        if any(kw in task_lower for kw in ['test', 'qa', 'verify', 'bug', 'fix bug', 'regression', 'validation']):
            return "qa_tester"

        # UI/UX related
        if any(kw in task_lower for kw in ['ui', 'ux', 'design', 'css', 'style', 'layout', 'interface', 'frontend', 'html', 'template']):
            return "ui_ux_engineer"

        # Database related
        if any(kw in task_lower for kw in ['database', 'db', 'schema', 'sql', 'migration', 'model', 'table', 'query']):
            return "database_admin"

        # Security related
        if any(kw in task_lower for kw in ['security', 'auth', 'authentication', 'authorization', 'encrypt', 'password', 'token']):
            return "security_reviewer"

        # Default to software engineer
        return "software_engineer"

    async def _mark_task_complete(self, task_text: str):
        """Mark a task as complete in TODO.md (async to avoid blocking).

        task_text can be either the raw text (with {ID} and [depends:]) or display_text.
        We try the raw text first, then fall back to display_text matching.
        """
        todo_path = os.path.join(self.project_path, "TODO.md")
        if not os.path.exists(todo_path):
            return

        async with self.todo_lock:
            async with aiofiles.open(todo_path, 'r', encoding='utf-8') as f:
                content = await f.read()

            # Try direct replacement first (works for raw text with {ID} and [depends:])
            old_task = f"- [ ] {task_text}"
            new_task = f"- [x] {task_text}"
            if old_task in content:
                content = content.replace(old_task, new_task, 1)
            else:
                # Fallback: find line containing display_text and check it off
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith('- [ ] ') and task_text in stripped:
                        lines[i] = line.replace('- [ ] ', '- [x] ', 1)
                        break
                content = '\n'.join(lines)

            async with aiofiles.open(todo_path, 'w', encoding='utf-8') as f:
                await f.write(content)

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Task completed",
            "details": task_text[:100]
        })

    async def continue_work(self) -> Dict[str, Any]:
        """Continue working on the current project (alias for start_work)."""
        return await self.start_work()

    async def _run_final_security_review(self) -> Dict[str, Any]:
        """Run a security review on all project files before completion."""
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Starting final security review",
            "details": "Reviewing all project files for security issues"
        })

        await self._send_message("info", "Running final security review...")

        # Collect all code files in the project
        code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.sql', '.sh', '.yml', '.yaml', '.json'}
        exclude_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build', 'QA'}

        files_to_review = []
        for root, dirs, files in os.walk(self.project_path):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in code_extensions:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.project_path)
                    files_to_review.append(rel_path)

        if not files_to_review:
            self._log_activity({
                "timestamp": datetime.now().isoformat(),
                "agent": "orchestrator",
                "action": "Security review skipped",
                "details": "No code files found to review"
            })
            return {"status": "complete", "result": "No code files to review"}

        # Limit to reasonable number of files
        if len(files_to_review) > 20:
            files_to_review = files_to_review[:20]
            self._log_activity({
                "timestamp": datetime.now().isoformat(),
                "agent": "orchestrator",
                "action": "Security review",
                "details": f"Reviewing first 20 files (total: {len(files_to_review)})"
            })

        try:
            await self._notify_agent_start("security_reviewer")
            result = await self.request_security_review(files_to_review)
            await self._notify_agent_complete("security_reviewer")

            if result["status"] == "complete":
                self._log_activity({
                    "timestamp": datetime.now().isoformat(),
                    "agent": "security_reviewer",
                    "action": "Security review complete",
                    "details": result.get("result", "Review completed")[:500]
                })
                await self._send_message("info", "Security review completed")

                # Add notes to QA notes file
                await self._add_qa_notes(
                    f"Security Review completed.\n\n{result.get('result', '')[:1000]}",
                    "Security Review Notes"
                )
            else:
                self._log_activity({
                    "timestamp": datetime.now().isoformat(),
                    "agent": "orchestrator",
                    "action": "Security review issue",
                    "details": result.get("result", "Unknown issue")[:200]
                })

            return result

        except Exception as e:
            error_msg = str(e).encode('ascii', errors='replace').decode('ascii')
            self._log_activity({
                "timestamp": datetime.now().isoformat(),
                "agent": "orchestrator",
                "action": "Security review error",
                "details": error_msg[:200]
            })
            await self._send_message("info", f"Security review encountered an error: {error_msg[:100]}")
            return {"status": "error", "result": error_msg}

    async def request_security_review(self, files: List[str]) -> Dict[str, Any]:
        """Request a security review for specified files."""
        reviewer = self.agents["security_reviewer"]

        review_task = f"""Please perform a security review of the following files:
{chr(10).join(files)}

Check for:
1. Security vulnerabilities (BLOCKING if found)
2. Code quality issues (ADVISORY)

Report any blocking issues that must be fixed before proceeding."""

        result = await reviewer.process_task(
            task=review_task,
            project_path=self.project_path,
            context="",
            orchestrator=self,
            config=self.config
        )

        return result

    def get_activity_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent activity log entries."""
        return self.activity_log[-limit:]

    def get_status(self) -> Dict[str, Any]:
        """Get the current orchestrator status."""
        return {
            "project_path": self.project_path,
            "agents": list(self.agents.keys()),
            "activity_count": len(self.activity_log),
            "pending_human_input": self.pending_human_input is not None,
            "config": self.config
        }

    async def _set_project_status(self, status: ProjectStatus, reason: str = ""):
        """Set the project workflow status and notify UI."""
        result = self.project_manager_core.set_workflow_status(
            name=self.project_name,
            new_status=status,
            agent="orchestrator",
            reason=reason
        )

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": f"Status changed to {status.value.upper()}",
            "details": reason
        })

        await self._send_message(
            "status_change",
            f"Project status: {status.value}",
            new_status=status.value,
            previous_status=result.get("previous_status"),
            reason=reason
        )

        return result

    def _normalize_testing_strategy(self) -> str:
        strategy = (self.testing_strategy or "critical_paths").lower().strip()
        strategy = strategy.replace(" ", "_").replace("-", "_")
        return strategy

    def _should_run_testing_phase(self) -> bool:
        if not self.quality_gates.get("run_tests", True):
            return False
        strategy = self._normalize_testing_strategy()
        if strategy in {"minimal", "smoke", "smoke_tests", "smoke_test"}:
            return False
        return True

    def _should_run_testing_phase_now(self) -> bool:
        if not self._should_run_testing_phase():
            return False
        return self._has_code_changes_since_last_review()

    async def _run_tests(self) -> Dict[str, Any]:
        """Run tests based on configured testing strategy."""
        strategy = self._normalize_testing_strategy()
        if not self.quality_gates.get("run_tests", True):
            return {"status": "skipped", "summary": "Testing skipped (quality gate disabled)."}

        if strategy == "minimal":
            self._log_activity({
                "timestamp": datetime.now().isoformat(),
                "agent": "orchestrator",
                "action": "Tests skipped",
                "details": "testing_strategy=minimal"
            })
            return {"status": "skipped", "summary": "Testing skipped (strategy: minimal)."}

        if strategy in {"critical_paths", "full_tdd"}:
            if not self._has_code_changes_since_last_review():
                return {"status": "skipped", "summary": "Testing skipped (no code changes since last QA)."}

        tests_found = self._detect_pytests()
        if not tests_found:
            summary = f"No tests found (strategy: {strategy})."
            if strategy == "full_tdd":
                self._log_activity({
                    "timestamp": datetime.now().isoformat(),
                    "agent": "orchestrator",
                    "action": "Tests failed",
                    "details": "No tests found for full_tdd"
                })
                return {"status": "failed", "summary": summary}

            self._log_activity({
                "timestamp": datetime.now().isoformat(),
                "agent": "orchestrator",
                "action": "Tests skipped",
                "details": summary
            })
            return {"status": "skipped", "summary": summary}

        cmd = ["pytest", "-q"]
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Running tests",
            "details": "pytest -q"
        })

        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            timeout = min(self.task_timeout, 300)
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            out = stdout.decode('utf-8', errors='replace').strip()
            err = stderr.decode('utf-8', errors='replace').strip()
            combined = out
            if err:
                combined = f"{out}\n{err}".strip()

            if process.returncode == 0:
                return {"status": "passed", "summary": combined or "pytest passed."}
            return {"status": "failed", "summary": combined or "pytest failed."}
        except asyncio.CancelledError:
            if process:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                await process.wait()
            raise
        except asyncio.TimeoutError:
            return {"status": "timeout", "summary": "pytest timed out."}
        except FileNotFoundError:
            return {"status": "error", "summary": "pytest not found. Install it to run tests."}
        except Exception as e:
            return {"status": "error", "summary": f"Test runner error: {str(e)[:200]}"}

    def _detect_pytests(self) -> bool:
        """Detect if pytest-style tests exist in the project."""
        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}]
            for name in files:
                if name.startswith("test_") and name.endswith(".py"):
                    return True
        return False

    def _quality_marker_path(self) -> str:
        return os.path.join(self.project_path, ".quality_gate.json")

    def _get_latest_code_mtime(self) -> float:
        code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.sql', '.sh', '.yml', '.yaml', '.json'}
        exclude_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build', 'QA'}
        latest = 0.0
        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in code_extensions:
                    try:
                        mtime = os.path.getmtime(os.path.join(root, file))
                        if mtime > latest:
                            latest = mtime
                    except OSError:
                        continue
        return latest

    def _has_code_changes_since_last_review(self) -> bool:
        latest = self._get_latest_code_mtime()
        if latest == 0.0:
            return False
        marker_path = self._quality_marker_path()
        if not os.path.exists(marker_path):
            return True
        try:
            with open(marker_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            last_mtime = float(data.get("last_code_mtime", 0.0))
            return latest > last_mtime
        except Exception:
            return True

    def _save_quality_marker(self):
        marker_path = self._quality_marker_path()
        data = {
            "last_code_mtime": self._get_latest_code_mtime(),
            "timestamp": datetime.now().isoformat()
        }
        try:
            with open(marker_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    async def _ensure_tests_exist(self, allow_update: bool = False) -> Dict[str, Any]:
        """Ask the Testing Agent to create or update minimal tests as needed."""
        tests_exist = self._detect_pytests()

        if tests_exist and not allow_update:
            return {"status": "skipped", "result": "Tests already exist; update not required."}

        try:
            await self._notify_agent_start("testing_agent")

            prompt = """Create or update a minimal pytest test suite for this project.

Requirements:
- Place tests under a `tests/` directory
- Ensure tests align with the current code after recent changes
- At least one test should assert basic project sanity (e.g., config loads, app imports)
- Keep tests fast and focused on critical paths
- If tests already exist, update them minimally; regenerate only if necessary
"""
            result = await self.agents["testing_agent"].process_task(
                task=prompt,
                project_path=self.project_path,
                context=self.memory.get_project_summary(),
                orchestrator=self,
                timeout=min(self.task_timeout, 300),
                config=self.config
            )
            return result
        except Exception:
            return {"status": "error", "result": "Testing agent failed to create/update tests."}
        finally:
            await self._notify_agent_complete("testing_agent")

    async def _run_testing_phase(self) -> Dict[str, Any]:
        """Run the dedicated testing phase before security review."""
        if not self._should_run_testing_phase():
            return {"status": "skipped", "result": "Testing phase skipped (strategy <= smoke or gate disabled)."}
        if not self._has_code_changes_since_last_review():
            return {"status": "skipped", "result": "Testing phase skipped (no code changes since last QA)."}

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Starting testing phase",
            "details": f"Testing strategy: {self._normalize_testing_strategy()}"
        })

        await self._send_message("info", "Running testing phase...")

        # Build or update tests
        prep_result = await self._ensure_tests_exist(allow_update=True)

        # Run tests
        test_result = await self._run_tests()
        self.last_test_result = test_result

        issues = []
        # Add issues from testing agent output if present
        if prep_result and prep_result.get("status") == "complete":
            prep_text = prep_result.get("result", "")
            issues.extend(self._parse_review_issues(prep_text))

        # Convert test failures into TODO issues
        if test_result.get("status") in {"failed", "error", "timeout"}:
            issues.append({
                "title": "[BLOCKING] Automated tests failed",
                "description": (test_result.get("summary", "") or "pytest failed").strip()[:400]
            })

        result_summary = f"TEST PREP: {prep_result.get('status')} | TEST RUN: {test_result.get('status')} - {test_result.get('summary', '')[:400]}"
        return {
            "status": "complete",
            "result": result_summary,
            "issues": issues,
            "test_result": test_result
        }

    async def _run_qa_review(self) -> Dict[str, Any]:
        """Run QA testing on the project."""
        if not self.quality_gates.get("run_qa_review", True):
            return {"status": "skipped", "result": "QA review skipped (quality gate disabled)."}
        if not self._has_code_changes_since_last_review():
            return {"status": "skipped", "result": "QA review skipped (no code changes since last QA)."}

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Starting QA review",
            "details": f"Playwright available: {self.playwright_available}"
        })

        await self._send_message("info", "Running QA review...")

        test_result = self.last_test_result or {"summary": "No automated tests were run in QA phase."}

        # Read spec for requirements verification
        spec_content = ""
        spec_path = os.path.join(self.project_path, "SPEC.md")
        if os.path.exists(spec_path):
            with open(spec_path, 'r', encoding='utf-8') as f:
                spec_content = f.read()

        # Build QA task
        mgmt_port = self.config.get("server_port", 8080)
        playwright_note = ""
        if self.playwright_available:
            playwright_note = f"""
PLAYWRIGHT BROWSER TESTING - MANDATORY PROCEDURE:

STEP 1 - KILL STALE SESSION (do this BEFORE any browser interaction):
  Call browser_close immediately. This shuts down any leftover browser from a previous session.
  If it errors (no browser open), that is fine -- ignore the error and continue.

STEP 2 - OPEN AND TEST:
  Use browser_navigate to open the application URL. This starts a clean browser session.
  - Use browser_take_screenshot to capture evidence (save to the QA folder)
  - Verify the UI matches the spec requirements
  - Port {mgmt_port} is reserved for the management interface. NEVER navigate to localhost:{mgmt_port}.
    If the project runs a web server, make sure it uses a DIFFERENT port (e.g. 3000, 5000, 5173, 8000, 9000, etc.).

STEP 3 - CLOSE BROWSER WHEN DONE (mandatory, do not skip):
  When ALL testing is complete, call browser_close as your LAST tool call.
  Do not leave the browser open.
"""

        qa_task = f"""Perform QA testing on this project to verify it meets the specification.

PROJECT SPECIFICATION:
{spec_content[:3000]}

TEST RESULTS:
{test_result.get("summary", "No tests were run.")}

TESTING INSTRUCTIONS:
1. Review what was implemented (check src/ folder)
2. Verify each requirement from the spec is met
3. Test critical user flows
4. Document any bugs or issues found
{playwright_note}

For each issue found, report:
- SEVERITY: BLOCKING / MAJOR / MINOR
- TITLE: Brief description
- DESCRIPTION: Detailed explanation
- EXPECTED: What should happen
- ACTUAL: What actually happens

If all tests pass, report "QA PASSED" with a summary of what was tested.
If issues are found, report them in the format above so they can be added to TODO."""

        try:
            await self._notify_agent_start("qa_tester")

            qa_agent = self.agents["qa_tester"]
            result = await qa_agent.process_task(
                task=qa_task,
                project_path=self.project_path,
                context=self.memory.get_project_summary(),
                orchestrator=self,
                timeout=self.task_timeout * 2,  # Give QA more time
                config=self.config
            )

            await self._notify_agent_complete("qa_tester")

            return result

        except Exception as e:
            await self._notify_agent_complete("qa_tester")
            error_msg = str(e).encode('ascii', errors='replace').decode('ascii')
            return {"status": "error", "result": error_msg}

    def _parse_review_issues(self, review_result: str) -> List[Dict[str, str]]:
        """Parse issues from security or QA review results."""
        issues = []
        lines = review_result.split('\n')

        current_issue = {}
        for line in lines:
            line_lower = line.lower().strip()

            # Look for issue markers
            if 'blocking:' in line_lower or 'major:' in line_lower:
                if current_issue:
                    issues.append(current_issue)
                severity = "BLOCKING" if "blocking" in line_lower else "MAJOR"
                title = line.split(':', 1)[-1].strip() if ':' in line else line.strip()
                current_issue = {"title": f"[{severity}] {title}", "description": ""}

            elif line_lower.startswith('- title:') or line_lower.startswith('title:'):
                if current_issue and current_issue.get("title"):
                    issues.append(current_issue)
                title = line.split(':', 1)[-1].strip()
                current_issue = current_issue or {"title": "", "description": ""}
                current_issue["title"] = title
                severity = current_issue.get("severity", "")
                if severity in ("BLOCKING", "MAJOR") and not title.upper().startswith(f"[{severity}]"):
                    current_issue["title"] = f"[{severity}] {title}".strip()

            elif line_lower.startswith('- description:') or line_lower.startswith('description:'):
                if current_issue:
                    current_issue["description"] = line.split(':', 1)[-1].strip()

            elif line_lower.startswith('- severity:') or line_lower.startswith('severity:'):
                severity = line.split(':', 1)[-1].strip().upper()
                if not current_issue:
                    current_issue = {"title": "", "description": ""}
                current_issue["severity"] = severity
                if severity in ("BLOCKING", "MAJOR") and current_issue.get("title"):
                    if not current_issue["title"].upper().startswith(f"[{severity}]"):
                        current_issue["title"] = f"[{severity}] {current_issue.get('title', '')}".strip()

        if current_issue and current_issue.get("title"):
            issues.append(current_issue)

        return issues

    async def _handle_review_issues(
        self,
        issues: List[Dict[str, str]],
        review_type: str
    ) -> bool:
        """
        Handle issues found during review.
        Returns True if issues were found and need to be addressed.
        """
        if not issues:
            return False

        # Add issues to TODO
        self.project_manager_core.add_review_issues_to_todo(
            name=self.project_name,
            issues=issues,
            review_type=review_type
        )

        # Set status back to WIP
        await self._set_project_status(
            ProjectStatus.WIP,
            f"{len(issues)} issues found during {review_type} review"
        )

        # Notify UI
        await self._send_message(
            "info",
            f"{review_type} found {len(issues)} issues. Added to TODO. Status reset to WIP."
        )

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": f"{review_type} issues added to TODO",
            "details": f"{len(issues)} issues need to be addressed"
        })

        return True

    async def _add_qa_notes(self, notes: str, section: str = "QA Review Notes"):
        """Add notes to the QA notes.md file."""
        self.project_manager_core.append_qa_notes(
            name=self.project_name,
            notes=notes,
            section=section,
            agent="qa_tester"
        )
