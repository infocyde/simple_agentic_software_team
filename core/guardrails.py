"""Guardrails - Configurable safety controls for agent actions."""

import os
import re
from typing import Dict, Any, List, Optional, Callable
from enum import Enum


class ActionType(Enum):
    """Types of actions agents can take."""
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    DELETE_FILE = "delete_file"
    RUN_COMMAND = "run_command"
    INSTALL_PACKAGE = "install_package"
    GIT_OPERATION = "git_operation"
    NETWORK_REQUEST = "network_request"
    DATABASE_OPERATION = "database_operation"


class ApprovalLevel(Enum):
    """Approval levels for actions."""
    ALLOW = "allow"  # Always allow
    WARN = "warn"  # Allow but log warning
    CONFIRM = "confirm"  # Require human confirmation
    DENY = "deny"  # Always deny


class Guardrails:
    """
    Manages safety guardrails for agent actions.
    Configurable per project or globally.
    """

    # Default rules - can be overridden per project
    DEFAULT_RULES = {
        # File operations
        "file_patterns_deny": [
            r"\.env$",  # Environment files
            r"\.env\..*$",
            r"credentials\..*$",
            r"secrets\..*$",
            r"\.pem$",
            r"\.key$",
            r"id_rsa",
        ],
        "file_patterns_warn": [
            r"config\..*$",
            r"settings\..*$",
        ],

        # Command patterns
        "commands_deny": [
            r"rm\s+-rf\s+/",  # Dangerous rm
            r"rm\s+-rf\s+\*",
            r":(){ :|:& };:",  # Fork bomb
            r"dd\s+if=",  # dd command
            r"mkfs\.",  # Format commands
            r">\s*/dev/",  # Writing to devices
            r"curl.*\|\s*bash",  # Piping to bash
            r"wget.*\|\s*bash",
        ],
        "commands_warn": [
            r"sudo\s+",
            r"npm\s+install\s+-g",
            r"pip\s+install\s+--user",
        ],

        # Git operations
        "git_deny": [
            r"push\s+.*--force",
            r"push\s+-f",
            r"reset\s+--hard",
        ],
        "git_warn": [
            r"push",  # Any push (human should review)
        ],

        # Network
        "network_deny": [
            r"0\.0\.0\.0",
            r"localhost.*delete",
            r"localhost.*drop",
        ],
    }

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.rules = {**self.DEFAULT_RULES}

        # Apply config overrides
        if "guardrails" in self.config:
            guardrails_config = self.config["guardrails"]

            # Override blocked operations
            if "blocked_operations" in guardrails_config:
                for op in guardrails_config["blocked_operations"]:
                    self._add_deny_rule(op)

            # Override required approvals
            if "require_approval_for" in guardrails_config:
                for op in guardrails_config["require_approval_for"]:
                    self._add_confirm_rule(op)

        # Callbacks for approval requests
        self.approval_callback: Optional[Callable] = None

    def _add_deny_rule(self, pattern: str):
        """Add a pattern to deny rules."""
        if "commands_deny" not in self.rules:
            self.rules["commands_deny"] = []
        self.rules["commands_deny"].append(pattern)

    def _add_confirm_rule(self, pattern: str):
        """Add a pattern to confirmation rules."""
        if "commands_confirm" not in self.rules:
            self.rules["commands_confirm"] = []
        self.rules["commands_confirm"].append(pattern)

    def check_file_operation(
        self,
        file_path: str,
        operation: str = "write"
    ) -> Dict[str, Any]:
        """Check if a file operation is allowed."""
        filename = os.path.basename(file_path)

        # Check deny patterns
        for pattern in self.rules.get("file_patterns_deny", []):
            if re.search(pattern, filename, re.IGNORECASE):
                return {
                    "allowed": False,
                    "level": ApprovalLevel.DENY,
                    "reason": f"File matches blocked pattern: {pattern}"
                }

        # Check warn patterns
        for pattern in self.rules.get("file_patterns_warn", []):
            if re.search(pattern, filename, re.IGNORECASE):
                return {
                    "allowed": True,
                    "level": ApprovalLevel.WARN,
                    "reason": f"File matches sensitive pattern: {pattern}"
                }

        return {
            "allowed": True,
            "level": ApprovalLevel.ALLOW,
            "reason": None
        }

    def check_command(self, command: str) -> Dict[str, Any]:
        """Check if a command is allowed."""
        # Check deny patterns
        for pattern in self.rules.get("commands_deny", []):
            if re.search(pattern, command, re.IGNORECASE):
                return {
                    "allowed": False,
                    "level": ApprovalLevel.DENY,
                    "reason": f"Command matches blocked pattern: {pattern}"
                }

        # Check confirm patterns
        for pattern in self.rules.get("commands_confirm", []):
            if re.search(pattern, command, re.IGNORECASE):
                return {
                    "allowed": False,
                    "level": ApprovalLevel.CONFIRM,
                    "reason": f"Command requires approval: {pattern}"
                }

        # Check warn patterns
        for pattern in self.rules.get("commands_warn", []):
            if re.search(pattern, command, re.IGNORECASE):
                return {
                    "allowed": True,
                    "level": ApprovalLevel.WARN,
                    "reason": f"Command matches sensitive pattern: {pattern}"
                }

        return {
            "allowed": True,
            "level": ApprovalLevel.ALLOW,
            "reason": None
        }

    def check_git_operation(self, git_command: str) -> Dict[str, Any]:
        """Check if a git operation is allowed."""
        # Check deny patterns
        for pattern in self.rules.get("git_deny", []):
            if re.search(pattern, git_command, re.IGNORECASE):
                return {
                    "allowed": False,
                    "level": ApprovalLevel.DENY,
                    "reason": f"Git operation blocked: {pattern}"
                }

        # Check warn patterns (git push should be reviewed)
        for pattern in self.rules.get("git_warn", []):
            if re.search(pattern, git_command, re.IGNORECASE):
                return {
                    "allowed": True,
                    "level": ApprovalLevel.WARN,
                    "reason": f"Git operation should be reviewed: {pattern}"
                }

        return {
            "allowed": True,
            "level": ApprovalLevel.ALLOW,
            "reason": None
        }

    def check_content_for_secrets(self, content: str) -> Dict[str, Any]:
        """Check if content contains potential secrets."""
        secret_patterns = [
            (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?[\w-]{20,}', "API Key"),
            (r'(?i)(secret|password|passwd|pwd)\s*[=:]\s*["\']?[^\s"\']{8,}', "Password/Secret"),
            (r'(?i)(token)\s*[=:]\s*["\']?[\w-]{20,}', "Token"),
            (r'(?i)Bearer\s+[\w-]{20,}', "Bearer Token"),
            (r'-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----', "Private Key"),
            (r'(?i)(aws_access_key_id|aws_secret_access_key)\s*[=:]\s*[\w/+]{20,}', "AWS Key"),
        ]

        findings = []
        for pattern, name in secret_patterns:
            if re.search(pattern, content):
                findings.append(name)

        if findings:
            return {
                "has_secrets": True,
                "findings": findings,
                "level": ApprovalLevel.DENY,
                "reason": f"Content may contain secrets: {', '.join(findings)}"
            }

        return {
            "has_secrets": False,
            "findings": [],
            "level": ApprovalLevel.ALLOW,
            "reason": None
        }

    def set_approval_callback(self, callback: Callable):
        """Set a callback for requesting human approval."""
        self.approval_callback = callback

    async def request_approval(self, action: str, details: str) -> bool:
        """Request human approval for an action."""
        if self.approval_callback:
            return await self.approval_callback(action, details)
        return False  # Default to deny if no callback

    def get_rules_summary(self) -> Dict[str, Any]:
        """Get a summary of current rules."""
        return {
            "file_deny_patterns": len(self.rules.get("file_patterns_deny", [])),
            "file_warn_patterns": len(self.rules.get("file_patterns_warn", [])),
            "command_deny_patterns": len(self.rules.get("commands_deny", [])),
            "command_warn_patterns": len(self.rules.get("commands_warn", [])),
            "git_deny_patterns": len(self.rules.get("git_deny", [])),
        }
