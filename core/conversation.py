"""Conversation Manager - Handles interactive Claude sessions for Q&A."""

import os
import asyncio
import subprocess
import json
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime


class ConversationManager:
    """
    Manages interactive conversations between users and agents.
    Spins up Claude Code sessions for Q&A flows like project kickoff.
    """

    def __init__(
        self,
        project_path: str,
        message_callback: Optional[Callable] = None,
        activity_callback: Optional[Callable] = None
    ):
        self.project_path = project_path
        self.message_callback = message_callback  # Send messages to frontend
        self.activity_callback = activity_callback  # Log activity
        self.conversation_history: List[Dict[str, str]] = []
        self.is_active = False
        self.pending_response = asyncio.Event()
        self.user_response: Optional[str] = None
        self.question_count = 0
        self.ready_for_spec = False

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
        """
        self.is_active = True
        self.conversation_history = []
        self.question_count = 0
        self.ready_for_spec = False

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

        # Start the conversation loop
        await self._run_conversation_loop(system_context, initial_request, num_questions)

    async def start_feature_conversation(self, feature_request: str, num_questions: int = 10):
        """
        Start a feature request conversation.
        """
        self.is_active = True
        self.conversation_history = []
        self.question_count = 0
        self.ready_for_spec = False

        # Load existing spec
        spec_path = os.path.join(self.project_path, "SPEC.md")
        existing_spec = ""
        if os.path.exists(spec_path):
            with open(spec_path, 'r', encoding='utf-8') as f:
                existing_spec = f.read()

        self.log_activity("Starting feature conversation", feature_request[:100])

        system_context = f"""You are the Project Manager (PM) in a Q&A conversation with a human user.

Existing project specification:
{existing_spec[:2000]}

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

        await self._run_conversation_loop(system_context, feature_request, num_questions)

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
            cmd = [
                "claude",
                "--print",
                "--dangerously-skip-permissions",
                "--model", "claude-opus-4-20250514",
                full_prompt
            ]

            # Set up environment with UTF-8 encoding for Windows
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'

            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120
            )

            output = stdout.decode('utf-8', errors='replace').strip()

            # Sanitize output to avoid encoding issues
            output = self._sanitize_output(output)

            if not output and stderr:
                error = stderr.decode('utf-8', errors='replace')
                self.log_activity("Claude error", error[:200])
                return None

            return output

        except asyncio.TimeoutError:
            self.log_activity("Claude timeout")
            return None
        except Exception as e:
            self.log_activity("Claude error", str(e))
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
        self.log_activity("Creating spec and todo documents")
        await self.send_message("system", "Creating SPEC.md and TODO.md...", "info")

        # Build final prompt to create documents
        create_prompt = self._build_document_creation_prompt()
        await self.send_thinking("project_manager")

        # Run Claude to create the documents (not --print, we want it to actually write files)
        # Use Opus for document creation - needs good reasoning
        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "--model", "claude-opus-4-20250514",
            create_prompt
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=180  # 3 minutes for document creation
            )

            output = stdout.decode('utf-8', errors='replace')
            self.log_activity("Documents created", output[:200] if output else "Complete")

        except asyncio.TimeoutError:
            self.log_activity("Document creation timeout")
            await self.send_message("system", "Document creation timed out. Please try again.", "error")
            self.is_active = False
            return
        except Exception as e:
            self.log_activity("Document creation error", str(e))
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

2. TODO.md - A task list with checkboxes for implementation:
   - IMPORTANT: Be CONCISE. Each task triggers a separate API call (costs tokens and rate limits).
   - Aim for the MINIMUM number of tasks needed - group related work into single tasks.
   - Maximum 50 tasks, but strongly prefer fewer (10-30 is ideal for most projects).
   - Each task should represent a meaningful chunk of work, not tiny steps.
   - Use [ ] for uncompleted tasks
   - Group related tasks into sections with ## headers

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
