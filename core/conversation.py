"""Conversation Manager - Handles interactive Claude sessions for Q&A."""

import os
import asyncio
import subprocess
import json
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from utils.cli_logger import log_cli_call
from utils.secrets import load_project_secrets


class ConversationManager:
    """
    Manages interactive conversations between users and agents.
    Spins up Claude Code sessions for Q&A flows like project kickoff.
    """

    def __init__(
        self,
        project_path: str,
        message_callback: Optional[Callable] = None,
        activity_callback: Optional[Callable] = None,
        status_callback: Optional[Callable] = None,
        uat_update_callback: Optional[Callable] = None
    ):
        self.project_path = project_path
        self.message_callback = message_callback  # Send messages to frontend
        self.activity_callback = activity_callback  # Log activity
        self.status_callback = status_callback  # Update project status
        self.uat_update_callback = uat_update_callback  # Resume work after UAT updates
        self.conversation_history: List[Dict[str, str]] = []
        self.is_active = False
        self.pending_response = asyncio.Event()
        self.user_response: Optional[str] = None
        self.question_count = 0
        self.ready_for_spec = False
        self.uat_mode = False
        self.uat_approved = False
        self.uat_update_requested = False
        # Token optimization: store full context once, trim progressively
        self._full_spec_context: str = ""
        self._spec_context_chars: int = 0
        # Conversation persistence for recovery
        self._state_file = os.path.join(project_path, ".conversation_state.json")
        self._conversation_type: str = ""
        self._initial_request: str = ""
        self._system_context: str = ""
        self._max_questions: int = 0

    def _save_conversation_state(self):
        """Save conversation state for recovery if process hangs."""
        state = {
            "conversation_type": self._conversation_type,
            "conversation_history": self.conversation_history,
            "question_count": self.question_count,
            "initial_request": self._initial_request,
            "system_context": self._system_context,
            "max_questions": self._max_questions,
            "full_spec_context": self._full_spec_context,
            "spec_context_chars": self._spec_context_chars,
            "uat_mode": self.uat_mode,
            "timestamp": datetime.now().isoformat()
        }
        try:
            with open(self._state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass  # Don't fail the conversation if state save fails

    def _load_conversation_state(self) -> Optional[Dict[str, Any]]:
        """Load saved conversation state if it exists."""
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _clear_conversation_state(self):
        """Clear saved state when conversation completes normally."""
        try:
            if os.path.exists(self._state_file):
                os.remove(self._state_file)
        except Exception:
            pass

    def log_activity(self, action: str, details: str = ""):
        """Log activity."""
        if self.activity_callback:
            self.activity_callback({
                "timestamp": datetime.now().isoformat(),
                "agent": "project_manager",
                "action": action,
                "details": details
            })

    async def send_message(self, agent: str, message: str, msg_type: str = "agent_message"):
        """Send a message to the frontend."""
        if self.message_callback:
            await self.message_callback({
                "type": msg_type,
                "agent": agent,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })

    async def send_thinking(self, agent: str):
        """Send thinking indicator to frontend."""
        if self.message_callback:
            await self.message_callback({
                "type": "agent_thinking",
                "agent": agent
            })

    async def start_kickoff_conversation(self, initial_request: str, num_questions: int = 18):
        """
        Start a project kickoff conversation.
        The PM will ask questions one at a time, gathering requirements.
        Resumes from saved state if a previous conversation was interrupted.
        """
        # Check for saved state to resume
        saved_state = self._load_conversation_state()
        if saved_state and saved_state.get("conversation_type") == "kickoff":
            await self._resume_conversation(saved_state)
            return

        self.is_active = True
        self.conversation_history = []
        self.question_count = 0
        self.ready_for_spec = False
        # Reset spec context (kickoff has no existing spec)
        self._full_spec_context = ""
        self._spec_context_chars = 0
        self._conversation_type = "kickoff"
        self._initial_request = initial_request
        self._max_questions = num_questions

        self.log_activity("Starting kickoff conversation", initial_request[:100])

        # Build the initial prompt for PM - STRICT role boundaries
        system_context = f"""You are the Project Manager (PM) in a Q&A conversation with a human user.

The user wants to build: "{initial_request}"

CRITICAL RULES:
1. You are ONLY the PM. You must NEVER write responses for the user.
2. Ask exactly ONE question, then STOP and wait.
3. Your response should ONLY contain your question - nothing else.
4. Do NOT simulate, imagine, or write what the user might say.
5. Do NOT answer your own questions.
6. Do NOT continue the conversation beyond asking one question.

Your goal: Ask {num_questions} clarifying questions (one at a time) about:
- Project scope and features
- Technical preferences
- Constraints and requirements
- User experience expectations

Question #{self.question_count + 1}: Ask your first question about the project."""

        self._system_context = system_context

        # Start the conversation loop
        await self._run_conversation_loop(system_context, initial_request, num_questions)

    async def start_feature_conversation(self, feature_request: str, num_questions: int = 10):
        """
        Start a feature request conversation.
        Resumes from saved state if a previous conversation was interrupted.
        """
        # Check for saved state to resume
        saved_state = self._load_conversation_state()
        if saved_state and saved_state.get("conversation_type") == "feature":
            await self._resume_conversation(saved_state)
            return

        self.is_active = True
        self.conversation_history = []
        self.question_count = 0
        self.ready_for_spec = False
        self._conversation_type = "feature"
        self._initial_request = feature_request
        self._max_questions = num_questions

        # Load existing spec and store for progressive trimming
        spec_path = os.path.join(self.project_path, "SPEC.md")
        existing_spec = ""
        if os.path.exists(spec_path):
            with open(spec_path, 'r', encoding='utf-8') as f:
                existing_spec = f.read()

        # Store full spec for first few questions, trim later
        self._full_spec_context = existing_spec[:2000]
        self._spec_context_chars = len(existing_spec)

        self.log_activity("Starting feature conversation", feature_request[:100])

        system_context = f"""You are the Project Manager (PM) in a Q&A conversation with a human user.

Existing project specification:
{{SPEC_CONTEXT}}

The user wants to add: "{feature_request}"

CRITICAL RULES:
1. You are ONLY the PM. You must NEVER write responses for the user.
2. Ask exactly ONE question, then STOP and wait.
3. Your response should ONLY contain your question - nothing else.
4. Do NOT simulate, imagine, or write what the user might say.
5. Do NOT answer your own questions.
6. Do NOT continue the conversation beyond asking one question.

Your goal: Ask {num_questions} clarifying questions (one at a time) about this feature.

Question #{self.question_count + 1}: Ask your first question about this feature."""

        self._system_context = system_context
        await self._run_conversation_loop(system_context, feature_request, num_questions)

    async def _resume_conversation(self, saved_state: Dict[str, Any]):
        """Resume a conversation from saved state."""
        self.is_active = True
        self.conversation_history = saved_state.get("conversation_history", [])
        self.question_count = saved_state.get("question_count", 0)
        self.ready_for_spec = False
        self._conversation_type = saved_state.get("conversation_type", "")
        self._initial_request = saved_state.get("initial_request", "")
        self._system_context = saved_state.get("system_context", "")
        self._max_questions = saved_state.get("max_questions", 18)
        self._full_spec_context = saved_state.get("full_spec_context", "")
        self._spec_context_chars = saved_state.get("spec_context_chars", 0)
        self.uat_mode = saved_state.get("uat_mode", False)

        self.log_activity("Resuming conversation", f"type={self._conversation_type}, q={self.question_count}")

        # Replay conversation history to frontend so user sees context
        for msg in self.conversation_history:
            if msg["role"] == "user":
                await self.send_message("user", msg["content"], "user_message")
            else:
                await self.send_message("project_manager", msg["content"])

        await self.send_message("system", f"Resumed conversation at question {self.question_count}. Continue where you left off.", "info")

        # Continue the appropriate conversation loop
        if self.uat_mode:
            await self._run_uat_conversation_loop(self._system_context, self._max_questions)
        else:
            await self._continue_conversation_loop(self._system_context, self._max_questions)

    async def _continue_conversation_loop(self, system_context: str, max_questions: int):
        """Continue a conversation loop from current state (for resume)."""
        try:
            while self.is_active and self.question_count < max_questions:
                self.pending_response.clear()
                await self.pending_response.wait()

                if not self.is_active:
                    break

                if self.ready_for_spec:
                    await self._finalize_conversation("")
                    break

                user_input = self.user_response
                self.user_response = None

                self.conversation_history.append({"role": "user", "content": user_input})
                self.question_count += 1

                # Save state after user input
                self._save_conversation_state()

                updated_context = system_context.replace(
                    f"Question #{self.question_count}:",
                    f"Question #{self.question_count + 1}:"
                )

                await self.send_thinking("project_manager")
                response = await self._ask_claude(updated_context, self.conversation_history)

                if not response:
                    await self.send_message("system", "Error getting response", "error")
                    break

                response = self._clean_response(response)
                self.conversation_history.append({"role": "assistant", "content": response})
                await self.send_message("project_manager", response)

                # Save state after PM response
                self._save_conversation_state()

            if self.question_count >= max_questions and self.is_active:
                await self.send_message(
                    "system",
                    f"Reached {max_questions} questions. Click 'Write Spec' when ready to generate documents.",
                    "info"
                )

        except Exception as e:
            self.log_activity("Conversation error", str(e))
            await self.send_message("system", f"Conversation error: {str(e)}", "error")

    async def _run_conversation_loop(self, system_context: str, initial_request: str, max_questions: int):
        """Run the conversation loop with Claude."""
        try:
            # Add initial context to history
            self.conversation_history.append({
                "role": "user",
                "content": f"Initial request: {initial_request}"
            })

            # Get first question from Claude
            await self.send_thinking("project_manager")
            response = await self._ask_claude(system_context, self.conversation_history)

            if not response:
                await self.send_message("system", "Error starting conversation", "error")
                return

            # Clean up response - remove any simulated user responses
            response = self._clean_response(response)

            # Send first question to user
            self.conversation_history.append({"role": "assistant", "content": response})
            await self.send_message("project_manager", response)
            self.question_count = 1

            # Save state after first question
            self._save_conversation_state()

            # Continue conversation loop - runs until user clicks "Write Spec" or max reached
            while self.is_active and self.question_count < max_questions:
                # Wait for user response
                self.pending_response.clear()
                await self.pending_response.wait()

                if not self.is_active:
                    break

                # Check if this is a signal to write the spec
                if self.ready_for_spec:
                    await self._finalize_conversation("")
                    break

                user_input = self.user_response
                self.user_response = None

                # Add user response to history
                self.conversation_history.append({"role": "user", "content": user_input})
                self.question_count += 1

                # Save state after user input
                self._save_conversation_state()

                # Update system context with current question number
                updated_context = system_context.replace(
                    f"Question #{self.question_count}:",
                    f"Question #{self.question_count + 1}:"
                )

                # Get next response from Claude
                await self.send_thinking("project_manager")
                response = await self._ask_claude(updated_context, self.conversation_history)

                if not response:
                    await self.send_message("system", "Error getting response", "error")
                    break

                # Clean up response
                response = self._clean_response(response)

                # Send next question
                self.conversation_history.append({"role": "assistant", "content": response})
                await self.send_message("project_manager", response)

                # Save state after PM response
                self._save_conversation_state()

            # If we hit max questions, notify user they can write spec
            if self.question_count >= max_questions and self.is_active:
                await self.send_message(
                    "system",
                    f"Reached {max_questions} questions. Click 'Write Spec' when ready to generate documents.",
                    "info"
                )

        except Exception as e:
            self.log_activity("Conversation error", str(e))
            await self.send_message("system", f"Conversation error: {str(e)}", "error")
        finally:
            pass  # Don't set is_active to False here - let write_spec or stop do it

    async def _ask_claude(self, system_context: str, history: List[Dict[str, str]]) -> Optional[str]:
        """Ask Claude a question and get a response."""
        # Progressive spec trimming: full context for first 2 exchanges, then trim
        # This saves ~1500 tokens per follow-up question
        if "{SPEC_CONTEXT}" in system_context:
            if len(history) <= 2:
                # First 1-2 exchanges: include full spec for grounding
                spec_injection = self._full_spec_context
            else:
                # Follow-ups: spec already in conversation history, just reference it
                spec_injection = f"[Spec provided above - {self._spec_context_chars} chars. Refer to conversation history.]"
            system_context = system_context.replace("{SPEC_CONTEXT}", spec_injection)

        # Build the full prompt
        prompt_parts = [system_context, "\n\n--- Conversation History ---\n"]

        for msg in history:
            role = "User" if msg["role"] == "user" else "You (PM)"
            prompt_parts.append(f"{role}: {msg['content']}\n")

        prompt_parts.append("\nYour response (ask ONE question only):")

        full_prompt = "\n".join(prompt_parts)

        # Call Claude CLI
        try:
            # PM conversations always use Opus for better reasoning
            # Prompt is piped via stdin to avoid Windows command-line length limits
            cmd = [
                "claude",
                "--print",
                "--dangerously-skip-permissions",
                "--model", "claude-opus-4-20250514"
            ]

            # Set up environment with UTF-8 encoding for Windows
            env = self._build_pm_env()

            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=full_prompt.encode('utf-8')),
                timeout=120
            )

            output = stdout.decode('utf-8', errors='replace').strip()

            # Sanitize output to avoid encoding issues
            output = self._sanitize_output(output)

            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM Conversation",
                prompt=full_prompt,
                model="claude-opus-4-20250514",
                status="complete" if output else "error",
                result_summary=output[:300] if output else "(no output)"
            )

            if not output and stderr:
                error = stderr.decode('utf-8', errors='replace')
                self.log_activity("Claude error", error[:200])
                return None

            return output

        except asyncio.TimeoutError:
            self.log_activity("Claude timeout")
            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM Conversation",
                prompt=full_prompt,
                model="claude-opus-4-20250514",
                status="timeout"
            )
            return None
        except Exception as e:
            self.log_activity("Claude error", str(e))
            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM Conversation",
                prompt=full_prompt,
                model="claude-opus-4-20250514",
                status="error",
                result_summary=str(e)[:300]
            )
            return None

    def _sanitize_output(self, text: str) -> str:
        """Remove or replace characters that might cause encoding issues."""
        if not text:
            return text
        replacements = {
            '\u2018': "'", '\u2019': "'",
            '\u201c': '"', '\u201d': '"',
            '\u2013': '-', '\u2014': '--',
            '\u2026': '...', '\u00a0': ' ',
        }
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        return text.encode('ascii', errors='replace').decode('ascii')

    def _build_pm_env(self) -> Dict[str, str]:
        """Build environment variables for PM subprocess calls."""
        env = os.environ.copy()
        env.update(load_project_secrets(self.project_path))
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        return env

    def _clean_response(self, response: str) -> str:
        """Clean up Claude's response to remove any simulated user responses."""
        # Common patterns where Claude might simulate user responses
        cutoff_patterns = [
            "\nUser:",
            "\nHuman:",
            "\nYou:",
            "\n**User:**",
            "\n**Human:**",
            "\nMe:",
            "\n[User",
            "\n---\nUser",
        ]

        cleaned = response
        for pattern in cutoff_patterns:
            if pattern.lower() in cleaned.lower():
                # Find the position and cut off everything after
                idx = cleaned.lower().find(pattern.lower())
                cleaned = cleaned[:idx].strip()

        return cleaned

    def trigger_spec_creation(self):
        """Signal that user wants to write the spec now."""
        self.ready_for_spec = True
        self.pending_response.set()

    def _check_for_document_creation(self, response: str) -> bool:
        """Check if Claude has created or is ready to create documents."""
        indicators = [
            "I have enough information",
            "I'll create the",
            "creating SPEC.md",
            "creating TODO.md",
            "I've created",
            "documents have been created",
            "SPEC.md and TODO.md",
            "Let me create"
        ]
        response_lower = response.lower()
        return any(ind.lower() in response_lower for ind in indicators)

    async def _finalize_conversation(self, final_response: str):
        """Finalize the conversation and ensure documents are created."""
        self._clear_conversation_state()  # Clear saved state on successful completion
        self.log_activity("Creating spec and todo documents")
        await self.send_message("system", "Creating SPEC.md and TODO.md...", "info")

        # Build final prompt to create documents
        create_prompt = self._build_document_creation_prompt()
        await self.send_thinking("project_manager")

        # Run Claude to create the documents (not --print, we want it to actually write files)
        # Use Opus for document creation - needs good reasoning
        # Prompt is piped via stdin to avoid Windows command-line length limits
        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "--model", "claude-opus-4-20250514"
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._build_pm_env()
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=create_prompt.encode('utf-8')),
                timeout=180  # 3 minutes for document creation
            )

            output = stdout.decode('utf-8', errors='replace')
            self.log_activity("Documents created", output[:200] if output else "Complete")

            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM Document Creation",
                prompt=create_prompt,
                model="claude-opus-4-20250514",
                status="complete",
                result_summary=output[:300] if output else ""
            )

        except asyncio.TimeoutError:
            self.log_activity("Document creation timeout")
            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM Document Creation",
                prompt=create_prompt,
                model="claude-opus-4-20250514",
                status="timeout"
            )
            await self.send_message("system", "Document creation timed out. Please try again.", "error")
            self.is_active = False
            return
        except Exception as e:
            self.log_activity("Document creation error", str(e))
            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM Document Creation",
                prompt=create_prompt,
                model="claude-opus-4-20250514",
                status="error",
                result_summary=str(e)[:300]
            )
            await self.send_message("system", f"Error creating documents: {str(e)}", "error")
            self.is_active = False
            return

        # Send completion message
        await self.send_message(
            "system",
            "Kickoff complete! SPEC.md and TODO.md have been created. Check the Spec and TODO tabs, then click 'Start Work' to begin.",
            "conversation_complete"
        )

        self.is_active = False
        self.log_activity("Conversation complete", f"Asked {self.question_count} questions")

    def _build_document_creation_prompt(self) -> str:
        """Build prompt for document creation based on conversation history."""
        prompt = """Based on the following conversation, create two files:

1. SPEC.md - A clear project specification including:
   - Project overview
   - Key features
   - Technical decisions
   - Any constraints or requirements mentioned

2. TODO.md - A task list with checkboxes and dependency tracking for implementation:
   - IMPORTANT: Be CONCISE. Each task triggers a separate API call (costs tokens and rate limits).
   - Aim for the MINIMUM number of tasks needed - group related work into single tasks.
   - Maximum 50 tasks, but strongly prefer fewer (10-30 is ideal for most projects).
   - Each task should represent a meaningful chunk of work, not tiny steps.
   - Use [ ] for uncompleted tasks
   - Group related tasks into sections with ## headers
   - DEPENDENCY FORMAT: Every task MUST have a unique numeric ID in curly braces, and may optionally declare dependencies:
     - `- [ ] {1} Initialize project structure`
     - `- [ ] {2} Install dependencies [depends: 1]`
     - `- [ ] {3} Create database schema [depends: 1]`
     - `- [ ] {4} Build API endpoints [depends: 3]`
     - `- [ ] {5} Build login form [depends: 3, 6]`
   - IDs are simple incrementing integers starting at 1
   - [depends: N, M] means this task is blocked until tasks N and M are complete
   - Tasks with no [depends:] tag can run immediately
   - Use dependencies to express real ordering constraints (e.g. schema before API, setup before implementation)
   - Tasks in the same section that are independent of each other need NO depends tag — they will run in parallel
   - PYTHON PROJECTS: If the project involves Python, the VERY FIRST task (ID {1}) in the TODO MUST be:
     `- [ ] {1} Create project-local .venv with uv (run: uv venv .venv), activate it, and install all required dependencies into it (run: uv pip install <packages>)`
     All subsequent tasks that run code, tests, or servers MUST depend on this task.
     All agents will work inside the project directory, so they must use the project's .venv — NOT any system Python or external environment.
     Playwright/QA testing should also run from within the project's .venv context.

--- Conversation ---
"""
        for msg in self.conversation_history:
            role = "User" if msg["role"] == "user" else "PM"
            prompt += f"\n{role}: {msg['content']}"

        prompt += "\n\n--- Create the files now ---"
        return prompt

    def receive_user_input(self, message: str):
        """Receive input from the user."""
        self.user_response = message
        self.pending_response.set()

    def stop(self):
        """Stop the conversation."""
        self.is_active = False
        self.pending_response.set()

    async def start_uat_conversation(self, num_questions: int = 100):
        """
        Start a UAT (User Acceptance Testing) conversation.
        The PM will present what was built and gather user feedback.
        User can approve, request changes, or report bugs.
        Resumes from saved state if a previous conversation was interrupted.
        """
        # Check for saved state to resume
        saved_state = self._load_conversation_state()
        if saved_state and saved_state.get("conversation_type") == "uat":
            await self._resume_conversation(saved_state)
            return

        self.is_active = True
        self.conversation_history = []
        self.question_count = 0
        self.ready_for_spec = False
        self.uat_mode = True
        self.uat_approved = False
        self.uat_changes_requested = []
        self._conversation_type = "uat"
        self._initial_request = "UAT"
        self._max_questions = num_questions

        # Load current spec and todo for context
        spec_path = os.path.join(self.project_path, "SPEC.md")
        todo_path = os.path.join(self.project_path, "TODO.md")
        summary_path = os.path.join(self.project_path, "SUMMARY.md")

        spec_content = ""
        todo_content = ""
        summary_content = ""

        if os.path.exists(spec_path):
            with open(spec_path, 'r', encoding='utf-8') as f:
                spec_content = f.read()

        if os.path.exists(todo_path):
            with open(todo_path, 'r', encoding='utf-8') as f:
                todo_content = f.read()

        if os.path.exists(summary_path):
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary_content = f.read()

        # Store full context for progressive trimming (spec + todo + summary)
        uat_context_parts = [
            f"PROJECT SPECIFICATION:\n{spec_content[:2000]}",
            f"COMPLETED TASKS:\n{todo_content[:1500]}"
        ]
        if summary_content:
            uat_context_parts.append(f"PROJECT SUMMARY:\n{summary_content[:1000]}")
        self._full_spec_context = "\n\n".join(uat_context_parts)
        self._spec_context_chars = len(spec_content) + len(todo_content) + len(summary_content)

        self.log_activity("Starting UAT conversation", "User acceptance testing")

        system_context = f"""You are the Project Manager (PM) conducting User Acceptance Testing (UAT) with the human user.

The project has completed development, testing, security review, and QA testing. Now you need the user's final approval.

{{SPEC_CONTEXT}}

CRITICAL RULES:
1. You are ONLY the PM. You must NEVER write responses for the user.
2. Ask exactly ONE question, then STOP and wait.
3. Your response should ONLY contain your question - nothing else.
4. Do NOT simulate, imagine, or write what the user might say.
5. Do NOT answer your own questions.

YOUR GOALS:
1. Present a brief summary of what was built
2. Ask the user to test/review the project
3. Gather feedback: bugs, issues, change requests, or approval
4. If changes requested, understand what needs to change
5. You can suggest deferring non-critical items to future iterations
6. Maximum {num_questions} questions before finalizing

RESPONSE HANDLING:
- If user says it's approved/looks good/complete: Acknowledge and prepare to mark as Done
- If user reports bugs/issues: Document them for TODO
- If user wants changes: Clarify what changes are needed
- You can suggest: "Would you like to defer [feature] to a future iteration?"

Question #{self.question_count + 1}: Start by briefly summarizing what was built and ask the user to review it."""

        self._system_context = system_context
        await self._run_uat_conversation_loop(system_context, num_questions)

    async def _run_uat_conversation_loop(self, system_context: str, max_questions: int):
        """Run the UAT conversation loop."""
        try:
            # Get first message from PM (summary and initial question)
            await self.send_thinking("project_manager")
            response = await self._ask_claude(system_context, self.conversation_history)

            if not response:
                await self.send_message("system", "Error starting UAT conversation", "error")
                return

            response = self._clean_response(response)
            self.conversation_history.append({"role": "assistant", "content": response})
            await self.send_message("project_manager", response)
            self.question_count = 1

            # Save state after first question
            self._save_conversation_state()

            # Conversation loop
            while self.is_active and self.question_count < max_questions:
                self.pending_response.clear()
                await self.pending_response.wait()

                if not self.is_active:
                    break

                # Check if user triggered finalization
                if self.ready_for_spec:
                    if self.uat_update_requested:
                        await self._process_uat_feedback()
                    else:
                        await self._finalize_uat_conversation()
                    break

                user_input = self.user_response
                self.user_response = None

                # Check for approval keywords
                if self._check_uat_approval(user_input):
                    self.uat_approved = True
                    await self._finalize_uat_conversation()
                    break

                self.conversation_history.append({"role": "user", "content": user_input})
                self.question_count += 1

                # Save state after user input
                self._save_conversation_state()

                # Update context with question count
                updated_context = system_context.replace(
                    f"Question #{self.question_count}:",
                    f"Question #{self.question_count + 1}:"
                )

                await self.send_thinking("project_manager")
                response = await self._ask_claude(updated_context, self.conversation_history)

                if not response:
                    await self.send_message("system", "Error getting response", "error")
                    break

                response = self._clean_response(response)

                # Check if PM detected approval in the conversation
                if self._check_pm_detected_approval(response):
                    self.uat_approved = True
                    self.conversation_history.append({"role": "assistant", "content": response})
                    await self.send_message("project_manager", response)
                    await self._finalize_uat_conversation()
                    break

                self.conversation_history.append({"role": "assistant", "content": response})
                await self.send_message("project_manager", response)

                # Save state after PM response
                self._save_conversation_state()

            # Max questions reached
            if self.question_count >= max_questions and self.is_active:
                await self.send_message(
                    "system",
                    f"Reached {max_questions} questions. Click 'Update Reqs' to apply changes or 'Done' to finalize.",
                    "info"
                )

        except Exception as e:
            self.log_activity("UAT conversation error", str(e))
            await self.send_message("system", f"UAT error: {str(e)}", "error")

    def _check_uat_approval(self, user_input: str) -> bool:
        """Check if user input indicates approval."""
        approval_phrases = [
            "approved", "looks good", "looks great", "lgtm",
            "ship it", "good to go", "complete", "done",
            "perfect", "accept", "approve", "all good",
            "no changes", "no issues", "everything works"
        ]
        input_lower = user_input.lower()
        return any(phrase in input_lower for phrase in approval_phrases)

    def _check_pm_detected_approval(self, response: str) -> bool:
        """Check if PM's response indicates they detected approval."""
        indicators = [
            "marking the project as complete",
            "mark this as done",
            "project is approved",
            "finalizing the project",
            "congratulations on completing",
            "ready to mark as complete"
        ]
        response_lower = response.lower()
        return any(ind in response_lower for ind in indicators)

    async def _finalize_uat_conversation(self):
        """Finalize the UAT conversation based on outcome."""
        self._clear_conversation_state()  # Clear saved state on successful completion
        self.log_activity("Finalizing UAT", f"Approved: {self.uat_approved}")

        if self.uat_approved:
            # User approved - project is done
            await self.send_message(
                "system",
                "Project approved! Generating runit.md and marking as complete.",
                "info"
            )

            await self._generate_runit_md()

            # Update status to DONE
            if self.status_callback:
                await self.status_callback("done", "User approved during UAT")

            # Send completion event
            if self.message_callback:
                await self.message_callback({
                    "type": "uat_complete",
                    "approved": True,
                    "message": "User approved the project",
                    "timestamp": datetime.now().isoformat()
                })

            self.is_active = False
            self.uat_mode = False
            self.log_activity("UAT complete", "Project approved by user")

        else:
            # Changes requested - update TODO and/or SPEC
            await self.send_message("system", "Processing your feedback and updating project...", "info")
            await self.send_thinking("project_manager")

            # Build prompt to analyze conversation and create tasks
            await self._process_uat_feedback()

    async def _process_uat_feedback(self):
        """Process UAT feedback and update TODO/SPEC."""
        self.uat_update_requested = False
        # Build prompt to analyze the conversation
        analyze_prompt = f"""Based on the following UAT conversation, analyze the user's feedback and determine what changes are needed.

--- UAT Conversation ---
"""
        for msg in self.conversation_history:
            role = "User" if msg["role"] == "user" else "PM"
            analyze_prompt += f"\n{role}: {msg['content']}"

        analyze_prompt += """

--- Instructions ---
Based on the conversation above:

1. If the user requested CHANGES or reported BUGS, create new tasks in TODO.md
   - Add a new section "## UAT Feedback (date)" with the issues
   - Use [ ] checkbox format for each task with unique IDs continuing from the highest existing ID
   - Format: `- [ ] {N} Task description` (and optionally `[depends: X]` if it depends on another new task)
   - Be specific about what needs to be done

2. If the user mentioned items to DEFER to future iterations (and agreed to defer):
   - Do NOT add these to TODO.md
   - Note them in a comment at the bottom of SPEC.md under "## Future Iterations"

3. If the spec needs updates based on feedback:
   - Update SPEC.md accordingly

4. After making changes, respond with a brief summary of what you updated.

Make the updates now."""

        try:
            # Run Claude to make the updates
            # Prompt is piped via stdin to avoid Windows command-line length limits
            cmd = [
                "claude",
                "--dangerously-skip-permissions",
                "--model", "claude-opus-4-20250514"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._build_pm_env()
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=analyze_prompt.encode('utf-8')),
                timeout=180
            )

            output = stdout.decode('utf-8', errors='replace')
            self.log_activity("UAT feedback processed", output[:200] if output else "Complete")

            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM UAT Feedback",
                prompt=analyze_prompt,
                model="claude-opus-4-20250514",
                status="complete",
                result_summary=output[:300] if output else ""
            )

            # Send completion message
            await self.send_message(
                "project_manager",
                "I've updated the project based on your feedback. The TODO has been updated with the requested changes.",
                "agent_message"
            )

            # Update status back to WIP
            if self.status_callback:
                await self.status_callback("wip", "Changes requested during UAT")

            # Send event to trigger status change back to WIP
            if self.message_callback:
                await self.message_callback({
                    "type": "uat_complete",
                    "approved": False,
                    "message": "Changes requested - returning to WIP",
                    "timestamp": datetime.now().isoformat()
                })

        except asyncio.TimeoutError:
            self.log_activity("UAT processing timeout")
            await self.send_message("system", "Processing timed out. Please try again.", "error")
        except Exception as e:
            self.log_activity("UAT processing error", str(e))
            await self.send_message("system", f"Error processing feedback: {str(e)}", "error")

        self.is_active = False
        self.uat_mode = False
        if self.uat_update_callback:
            await self.uat_update_callback()

    def trigger_uat_completion(self):
        """Signal that UAT should be finalized (user clicked Complete UAT)."""
        self.ready_for_spec = True
        self.pending_response.set()

    def trigger_uat_update(self):
        """Signal that UAT feedback should update requirements and resume work."""
        self.uat_update_requested = True
        self.ready_for_spec = True
        self.pending_response.set()

    def trigger_uat_done(self):
        """Signal that UAT is approved and should be finalized."""
        self.uat_approved = True
        self.ready_for_spec = True
        self.pending_response.set()

    async def _generate_runit_md(self):
        """Generate run instructions in runit.md."""
        runit_path = os.path.join(self.project_path, "runit.md")
        if os.path.exists(runit_path):
            self.log_activity("runit.md already exists", "Skipping generation")
            return

        prompt = """Create a file named runit.md in this project with clear instructions on how to build and run this project.

Include:
1. Local development setup
2. Build steps (if applicable)
3. Production run/deploy steps (if applicable)

If details are unknown, note reasonable assumptions and how to verify. Keep it concise.

Write the runit.md file now.
"""
        # Prompt is piped via stdin to avoid Windows command-line length limits
        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "--model", "claude-opus-4-20250514"
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._build_pm_env()
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(input=prompt.encode('utf-8')), timeout=180)
            output = stdout.decode('utf-8', errors='replace')
            self.log_activity("runit.md generated", output[:200] if output else "Complete")
            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM RunIt Generation",
                prompt=prompt,
                model="claude-opus-4-20250514",
                status="complete",
                result_summary=output[:300] if output else ""
            )
        except asyncio.TimeoutError:
            self.log_activity("runit.md generation timeout")
            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM RunIt Generation",
                prompt=prompt,
                model="claude-opus-4-20250514",
                status="timeout"
            )
            await self.send_message("system", "runit.md generation timed out.", "error")
        except Exception as e:
            self.log_activity("runit.md generation error", str(e))
            await log_cli_call(
                project_path=self.project_path,
                agent_name="project_manager",
                agent_role="PM RunIt Generation",
                prompt=prompt,
                model="claude-opus-4-20250514",
                status="error",
                result_summary=str(e)[:300]
            )
            await self.send_message("system", f"Error generating runit.md: {str(e)}", "error")
