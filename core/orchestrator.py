"""Orchestrator - Coordinates the agent team and manages task flow."""

import os
import json
import asyncio
import aiofiles
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from enum import Enum

from agents import (
    ProjectManagerAgent,
    SoftwareEngineerAgent,
    UIUXEngineerAgent,
    DatabaseAdminAgent,
    SecurityReviewerAgent
)
from .memory import MemoryManager


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

        # Pending human input requests
        self.pending_human_input: Optional[Dict[str, Any]] = None
        self.human_input_event = asyncio.Event()

        # Work state
        self.is_working = False
        self.pause_requested = False
        self.total_failures = 0  # Track total failures for critical error detection

        # User escalation state
        self.pending_user_decision = None
        self.user_decision_event = asyncio.Event()
        self.user_decision_response = None

        # Parallel execution settings
        exec_config = config.get('execution', {})
        self.max_concurrent = exec_config.get('max_concurrent_agents', 3)
        self.task_timeout = exec_config.get('task_timeout_seconds', 120)
        self.max_task_retries = exec_config.get('max_task_retries', 3)
        self.semaphore = asyncio.Semaphore(self.max_concurrent)

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
            )
        }

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
        Uses quick heuristics first, then PM for uncertain cases.
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
        try:
            pm = self.agents["project_manager"]
            estimate_prompt = f"""Quickly estimate the complexity of this task. Reply with ONLY one word: small, medium, or large.

Task: {task[:300]}

Criteria:
- small: Simple change, single file, < 5 minutes work
- medium: Moderate change, few files, 5-30 minutes work
- large: Complex change, multiple files/systems, > 30 minutes work

Reply with one word only:"""

            result = await pm.process_task(
                task=estimate_prompt,
                project_path=self.project_path,
                context="",
                orchestrator=self,
                timeout=30  # Quick timeout for estimation
            )

            if result["status"] == "complete":
                response = result["result"].strip().lower()
                if "small" in response:
                    return "small"
                elif "large" in response:
                    return "large"
                return "medium"
        except Exception:
            pass

        return "medium"  # Default to medium if estimation fails

    async def _split_large_task(self, task: str) -> List[str]:
        """Split a large task into smaller subtasks."""
        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": "Splitting large task",
            "details": task[:100]
        })

        pm = self.agents["project_manager"]

        split_prompt = f"""This task is too large and needs to be split into smaller, independent subtasks.

Original task: {task}

Please split this into 2-4 smaller subtasks that:
1. Can each be completed independently
2. Together accomplish the original goal
3. Are specific and actionable

Reply with ONLY the subtasks, one per line, no numbering or bullets. Each line should be a complete task description."""

        try:
            result = await pm.process_task(
                task=split_prompt,
                project_path=self.project_path,
                context="",
                orchestrator=self,
                timeout=60
            )

            if result["status"] == "complete":
                subtasks = []
                for line in result["result"].strip().split('\n'):
                    line = line.strip()
                    # Remove common prefixes
                    line = line.lstrip('0123456789.-) ')
                    if line and len(line) > 10:
                        subtasks.append(line)

                if len(subtasks) >= 2:
                    return subtasks[:4]  # Max 4 subtasks
        except Exception:
            pass

        # Fallback: return original task if splitting fails
        return [task]

    async def _replace_task_with_subtasks(self, original_task: str, subtasks: List[str]):
        """Replace a task in TODO.md with its subtasks."""
        todo_path = os.path.join(self.project_path, "TODO.md")
        if not os.path.exists(todo_path):
            return

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
        """Use PM to suggest a simpler version of a failed task."""
        pm = self.agents["project_manager"]

        simplify_prompt = f"""A task has failed and we need a simpler version.

Original task: {original_task}
Error encountered: {error[:300]}

Please suggest a simpler, more focused version of this task that:
1. Accomplishes the core goal
2. Avoids the complexity that caused the error
3. Can be done in a single step

Respond with ONLY the new task description, nothing else."""

        try:
            result = await pm.process_task(
                task=simplify_prompt,
                project_path=self.project_path,
                context="",
                orchestrator=self,
                timeout=60
            )

            if result["status"] == "complete":
                new_task = result["result"].strip()
                # Clean up - remove quotes if present
                new_task = new_task.strip('"\'')
                return new_task
        except Exception:
            pass

        # Fallback: just simplify by truncating
        return f"[SIMPLIFIED] {original_task[:50]}..."

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
            orchestrator=self
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

        # Execute with retry logic
        retries = 0

        while retries < self.max_task_retries:
            try:
                # Notify UI that agent is starting
                await self._notify_agent_start(agent_name)

                # Use semaphore to limit concurrent agents
                async with self.semaphore:
                    result = await agent.process_task(
                        task=task,
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
                    self.total_failures += 1
                    self._log_activity({
                        "timestamp": datetime.now().isoformat(),
                        "agent": "orchestrator",
                        "action": f"Timeout ({retries + 1}/{self.max_task_retries})",
                        "details": f"Task timed out after {self.task_timeout}s"
                    })
                    # Log timeout to error_log.md
                    await self._log_error(
                        error_type="timeout",
                        task=task,
                        error_details=f"Task timed out after {self.task_timeout}s (attempt {retries + 1}/{self.max_task_retries})",
                        agent=agent_name
                    )

            except Exception as e:
                await self._notify_agent_complete(agent_name)
                self.total_failures += 1
                error_msg = str(e).encode('ascii', errors='replace').decode('ascii')
                self._log_activity({
                    "timestamp": datetime.now().isoformat(),
                    "agent": "orchestrator",
                    "action": f"Task error ({retries + 1}/{self.max_task_retries})",
                    "details": error_msg[:200]
                })
                # Log exception to error_log.md
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

    async def start_project_kickoff(self, initial_request: str) -> Dict[str, Any]:
        """Start a new project with the PM asking kickoff questions."""
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
After gathering enough information (15-20 questions), create the SPEC.md and TODO.md files."""

        result = await pm.process_task(
            task=kickoff_task,
            project_path=self.project_path,
            context="",
            orchestrator=self
        )

        return result

    async def start_feature_request(self, feature_request: str) -> Dict[str, Any]:
        """Handle a new feature request on an existing project."""
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
Ask ONE question at a time. After gathering enough information, update SPEC.md and TODO.md."""

        result = await pm.process_task(
            task=feature_task,
            project_path=self.project_path,
            context=self.memory.get_project_summary(),
            orchestrator=self
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

    def _parse_todo_tasks(self) -> List[Dict[str, Any]]:
        """Parse TODO.md and return list of tasks with their status."""
        todo_path = os.path.join(self.project_path, "TODO.md")
        if not os.path.exists(todo_path):
            return []

        with open(todo_path, 'r', encoding='utf-8') as f:
            content = f.read()

        tasks = []
        current_section = "General"

        for line in content.split('\n'):
            line = line.strip()

            # Detect section headers
            if line.startswith('## '):
                current_section = line[3:].strip()
                continue

            # Parse task items
            if line.startswith('- [ ] '):
                tasks.append({
                    "text": line[6:].strip(),
                    "completed": False,
                    "section": current_section
                })
            elif line.startswith('- [x] ') or line.startswith('- [X] '):
                tasks.append({
                    "text": line[6:].strip(),
                    "completed": True,
                    "section": current_section
                })

        return tasks

    def _get_next_task(self) -> Optional[Dict[str, Any]]:
        """Get the next uncompleted task from TODO.md."""
        tasks = self._parse_todo_tasks()
        for task in tasks:
            if not task["completed"]:
                return task
        return None

    def _get_parallel_tasks(self, max_tasks: int = None) -> List[Dict[str, Any]]:
        """
        Get a batch of tasks that can run in parallel.
        Tasks in the same section are considered parallelizable.
        """
        if max_tasks is None:
            max_tasks = self.max_concurrent

        tasks = self._parse_todo_tasks()
        uncompleted = [t for t in tasks if not t["completed"]]

        if not uncompleted:
            return []

        # Get tasks from the same section (they're likely independent)
        first_section = uncompleted[0]["section"]
        same_section = [t for t in uncompleted if t["section"] == first_section]

        return same_section[:max_tasks]

    async def _execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single task and return the result."""
        task_text = task["text"]
        start_time = datetime.now()

        # Log task start with timestamp
        self._log_activity({
            "timestamp": start_time.isoformat(),
            "agent": "orchestrator",
            "action": "Task started",
            "details": f"[{start_time.strftime('%H:%M:%S')}] {task_text[:80]}..."
        })

        # Estimate complexity
        complexity = await self._estimate_task_complexity(task_text)

        self._log_activity({
            "timestamp": datetime.now().isoformat(),
            "agent": "orchestrator",
            "action": f"Task complexity: {complexity.upper()}",
            "details": task_text[:50]
        })

        # If task is large, split it into subtasks
        if complexity == "large":
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

        result = await self.assign_task(
            agent_name=agent_name,
            task=task_text,
            context=f"Section: {task['section']}\n\n" + self.memory.get_context_for_task(task_text, section=task['section'])
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

        return {"task": task, "result": result, "agent": agent_name}

    async def start_work(self) -> Dict[str, Any]:
        """Start working through TODO tasks with parallel execution and self-healing."""
        if self.is_working:
            return {"status": "error", "result": "Work already in progress"}

        self.is_working = True
        self.pause_requested = False
        self.total_failures = 0
        skipped_tasks = set()

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

                        # Run security review before marking complete
                        await self._run_final_security_review()

                        await self._send_message("work_complete", "All tasks in TODO.md are complete!")
                        break

                self._log_activity({
                    "timestamp": datetime.now().isoformat(),
                    "agent": "orchestrator",
                    "action": f"Running {len(tasks)} task(s) in parallel",
                    "details": ", ".join([t["text"][:30] + "..." for t in tasks])
                })

                # Execute tasks in parallel
                task_coroutines = [self._execute_task(task) for task in tasks]
                results = await asyncio.gather(*task_coroutines, return_exceptions=True)

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
                        await self._mark_task_complete(task["text"])
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
        """Mark a task as complete in TODO.md (async to avoid blocking)."""
        todo_path = os.path.join(self.project_path, "TODO.md")
        if not os.path.exists(todo_path):
            return

        async with aiofiles.open(todo_path, 'r', encoding='utf-8') as f:
            content = await f.read()

        # Replace the unchecked task with checked
        old_task = f"- [ ] {task_text}"
        new_task = f"- [x] {task_text}"
        content = content.replace(old_task, new_task)

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

    async def _run_final_security_review(self):
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
        exclude_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build'}

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
            return

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
            else:
                self._log_activity({
                    "timestamp": datetime.now().isoformat(),
                    "agent": "orchestrator",
                    "action": "Security review issue",
                    "details": result.get("result", "Unknown issue")[:200]
                })

        except Exception as e:
            error_msg = str(e).encode('ascii', errors='replace').decode('ascii')
            self._log_activity({
                "timestamp": datetime.now().isoformat(),
                "agent": "orchestrator",
                "action": "Security review error",
                "details": error_msg[:200]
            })
            await self._send_message("info", f"Security review encountered an error: {error_msg[:100]}")

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
            orchestrator=self
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
