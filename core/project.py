"""Project Manager - Handles project creation and management."""

import os
import json
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum


class ProjectStatus(Enum):
    """Project workflow status states."""
    INITIALIZED = "initialized"
    WIP = "wip"
    SECURITY_REVIEW = "security_review"
    QA = "qa"
    UAT = "uat"  # User Acceptance Testing - human review before Done
    DONE = "done"

    @classmethod
    def from_string(cls, value: str) -> "ProjectStatus":
        """Convert string to ProjectStatus enum."""
        for status in cls:
            if status.value == value.lower():
                return status
        return cls.INITIALIZED

    @classmethod
    def get_order(cls) -> List["ProjectStatus"]:
        """Get the status progression order."""
        return [
            cls.INITIALIZED,
            cls.WIP,
            cls.SECURITY_REVIEW,
            cls.QA,
            cls.UAT,
            cls.DONE
        ]


class ProjectManager:
    """
    Manages project directories and their lifecycle.
    Handles creation, listing, and status of projects.
    """

    def __init__(self, base_path: str):
        """
        Initialize the project manager.

        Args:
            base_path: The master directory containing all projects
        """
        self.base_path = base_path
        self.projects_dir = os.path.join(base_path, "projects")
        os.makedirs(self.projects_dir, exist_ok=True)

    def create_project(self, name: str, init_git: bool = True, quality_gates: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
        """
        Create a new project directory with initial structure.

        Args:
            name: Project name (will be sanitized for filesystem)
            init_git: Whether to initialize a git repository

        Returns:
            Dict with project info and path
        """
        # Sanitize name for filesystem
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())
        project_path = os.path.join(self.projects_dir, safe_name)

        if os.path.exists(project_path):
            return {
                "status": "error",
                "message": f"Project '{safe_name}' already exists",
                "path": project_path
            }

        # Create project directory structure
        os.makedirs(project_path)
        os.makedirs(os.path.join(project_path, "src"), exist_ok=True)

        # Create initial files
        self._create_initial_files(project_path, name, quality_gates=quality_gates)

        # Initialize git if requested
        if init_git:
            self._init_git(project_path)

        return {
            "status": "success",
            "message": f"Project '{name}' created",
            "path": project_path,
            "name": safe_name
        }

    def _create_initial_files(self, project_path: str, display_name: str, quality_gates: Optional[Dict[str, bool]] = None):
        """Create initial project files."""
        # Create placeholder SPEC.md
        spec_content = f"""# {display_name}

## Overview
*To be filled during project kickoff*

## Requirements
*To be defined*

## Technical Decisions
*To be documented*
"""
        with open(os.path.join(project_path, "SPEC.md"), 'w') as f:
            f.write(spec_content)

        # Create empty TODO.md
        todo_content = f"""# {display_name} - TODO

## Tasks
*Tasks will be added during project kickoff*
"""
        with open(os.path.join(project_path, "TODO.md"), 'w') as f:
            f.write(todo_content)

        # Create MEMORY.md
        memory_content = """# Project Memory

This file tracks decisions, actions, and lessons learned.

## Decisions

## Actions Log

## Lessons Learned
"""
        with open(os.path.join(project_path, "MEMORY.md"), 'w') as f:
            f.write(memory_content)

        # Create STATUS.json for workflow tracking
        status_data = {
            "current_status": ProjectStatus.INITIALIZED.value,
            "history": [
                {
                    "status": ProjectStatus.INITIALIZED.value,
                    "timestamp": datetime.now().isoformat(),
                    "agent": "system",
                    "reason": "Project created"
                }
            ],
            "security_review_passed": False,
            "qa_passed": False,
            "review_cycles": 0,
            "quality_gates": quality_gates or {
                "run_security_review": True,
                "run_qa_review": True,
                "run_tests": True
            }
        }
        with open(os.path.join(project_path, "STATUS.json"), 'w') as f:
            json.dump(status_data, f, indent=2)

        # Create QA directory for test artifacts
        os.makedirs(os.path.join(project_path, "QA"), exist_ok=True)

        # Create initial QA notes file
        qa_notes_content = f"""# QA Notes - {display_name}

## Overview
This file contains observations and notes from QA and Security reviews.

## Security Review Notes

## QA Review Notes

## Screenshots
Screenshots are stored in this QA folder with timestamps.

"""
        with open(os.path.join(project_path, "QA", "notes.md"), 'w') as f:
            f.write(qa_notes_content)

        # Create .gitignore
        gitignore_content = """# Dependencies
node_modules/
__pycache__/
*.pyc
.venv/
venv/

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Environment
.env
.env.local

# Build
dist/
build/
*.egg-info/
"""
        with open(os.path.join(project_path, ".gitignore"), 'w') as f:
            f.write(gitignore_content)

    def _init_git(self, project_path: str):
        """Initialize a git repository in the project directory."""
        try:
            subprocess.run(
                ["git", "init"],
                cwd=project_path,
                capture_output=True,
                check=True
            )
            # Initial commit
            subprocess.run(
                ["git", "add", "."],
                cwd=project_path,
                capture_output=True,
                check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial project setup"],
                cwd=project_path,
                capture_output=True,
                check=True
            )
        except subprocess.CalledProcessError:
            pass  # Git init failed, continue without it

    def list_projects(self) -> List[Dict[str, Any]]:
        """List all projects with their status."""
        projects = []

        if not os.path.exists(self.projects_dir):
            return projects

        for name in os.listdir(self.projects_dir):
            project_path = os.path.join(self.projects_dir, name)
            if os.path.isdir(project_path):
                projects.append(self.get_project_status(name))

        return projects

    def get_project_status(self, name: str) -> Dict[str, Any]:
        """Get the status of a specific project."""
        project_path = os.path.join(self.projects_dir, name)

        if not os.path.exists(project_path):
            return {"status": "error", "message": f"Project '{name}' not found"}

        status = {
            "name": name,
            "path": project_path,
            "has_spec": os.path.exists(os.path.join(project_path, "SPEC.md")),
            "has_todo": os.path.exists(os.path.join(project_path, "TODO.md")),
            "has_memory": os.path.exists(os.path.join(project_path, "MEMORY.md")),
            "has_qa_folder": os.path.exists(os.path.join(project_path, "QA")),
        }

        # Get workflow status
        workflow_status = self.get_workflow_status(name)
        status["workflow_status"] = workflow_status.get("current_status", "initialized")
        status["security_review_passed"] = workflow_status.get("security_review_passed", False)
        status["qa_passed"] = workflow_status.get("qa_passed", False)
        status["review_cycles"] = workflow_status.get("review_cycles", 0)

        # Parse TODO for completion status
        todo_path = os.path.join(project_path, "TODO.md")
        if os.path.exists(todo_path):
            with open(todo_path, 'r') as f:
                todo_content = f.read()
            completed = todo_content.count("[x]")
            pending = todo_content.count("[ ]")
            status["todo_completed"] = completed
            status["todo_pending"] = pending
            status["todo_total"] = completed + pending

        # Check for SUMMARY.md (project complete)
        status["has_summary"] = os.path.exists(os.path.join(project_path, "SUMMARY.md"))

        # Get git status if available
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_path,
                capture_output=True,
                text=True
            )
            status["git_changes"] = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
        except (subprocess.CalledProcessError, FileNotFoundError):
            status["git_changes"] = None

        return status

    def get_project_path(self, name: str) -> Optional[str]:
        """Get the full path to a project directory."""
        project_path = os.path.join(self.projects_dir, name)
        return project_path if os.path.exists(project_path) else None

    def delete_project(self, name: str, confirm: bool = False) -> Dict[str, Any]:
        """Delete a project (requires confirmation)."""
        if not confirm:
            return {
                "status": "error",
                "message": "Deletion requires confirmation"
            }

        project_path = os.path.join(self.projects_dir, name)
        if not os.path.exists(project_path):
            return {
                "status": "error",
                "message": f"Project '{name}' not found"
            }

        import shutil
        shutil.rmtree(project_path)

        return {
            "status": "success",
            "message": f"Project '{name}' deleted"
        }

    def get_workflow_status(self, name: str) -> Dict[str, Any]:
        """
        Get the current workflow status of a project.

        Args:
            name: Project name

        Returns:
            Dict with current status, history, and review states
        """
        project_path = os.path.join(self.projects_dir, name)
        status_file = os.path.join(project_path, "STATUS.json")

        if not os.path.exists(status_file):
            # Legacy project without STATUS.json - create one
            self._create_status_file(project_path, name)

        try:
            with open(status_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {
                "current_status": ProjectStatus.INITIALIZED.value,
                "history": [],
                "security_review_passed": False,
                "qa_passed": False,
                "review_cycles": 0,
                "quality_gates": {
                    "run_security_review": True,
                    "run_qa_review": True,
                    "run_tests": True
                }
            }

    def set_workflow_status(
        self,
        name: str,
        new_status: ProjectStatus,
        agent: str = "system",
        reason: str = ""
    ) -> Dict[str, Any]:
        """
        Set the workflow status of a project.

        Args:
            name: Project name
            new_status: The new status to set
            agent: The agent/user making the change
            reason: Reason for the status change

        Returns:
            Dict with updated status info
        """
        project_path = os.path.join(self.projects_dir, name)
        status_file = os.path.join(project_path, "STATUS.json")

        # Get current status
        current_data = self.get_workflow_status(name)
        old_status = current_data.get("current_status", ProjectStatus.INITIALIZED.value)

        # Update status
        current_data["current_status"] = new_status.value

        # Add to history
        history_entry = {
            "status": new_status.value,
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "reason": reason,
            "previous_status": old_status
        }
        current_data["history"].append(history_entry)

        # Track review cycles (when going back to WIP from review stages)
        if new_status == ProjectStatus.WIP and old_status in [
            ProjectStatus.SECURITY_REVIEW.value,
            ProjectStatus.QA.value
        ]:
            current_data["review_cycles"] = current_data.get("review_cycles", 0) + 1

        # Reset review flags if going back to WIP
        if new_status == ProjectStatus.WIP:
            current_data["security_review_passed"] = False
            current_data["qa_passed"] = False

        # Set review passed flags
        if new_status == ProjectStatus.QA:
            current_data["security_review_passed"] = True
        if new_status == ProjectStatus.DONE:
            current_data["qa_passed"] = True

        # Save updated status
        with open(status_file, 'w') as f:
            json.dump(current_data, f, indent=2)

        return {
            "status": "success",
            "previous_status": old_status,
            "new_status": new_status.value,
            "history_entry": history_entry
        }

    def _create_status_file(self, project_path: str, name: str):
        """Create STATUS.json for a legacy project."""
        status_data = {
            "current_status": ProjectStatus.INITIALIZED.value,
            "history": [
                {
                    "status": ProjectStatus.INITIALIZED.value,
                    "timestamp": datetime.now().isoformat(),
                    "agent": "system",
                    "reason": "Status file created for legacy project"
                }
            ],
            "security_review_passed": False,
            "qa_passed": False,
            "review_cycles": 0,
            "quality_gates": {
                "run_security_review": True,
                "run_qa_review": True,
                "run_tests": True
            }
        }

        # Check if project appears to be complete
        if os.path.exists(os.path.join(project_path, "SUMMARY.md")):
            status_data["current_status"] = ProjectStatus.DONE.value
            status_data["security_review_passed"] = True
            status_data["qa_passed"] = True

        with open(os.path.join(project_path, "STATUS.json"), 'w') as f:
            json.dump(status_data, f, indent=2)

    def get_quality_gates(self, name: str) -> Dict[str, bool]:
        """Get per-project quality gates."""
        status = self.get_workflow_status(name)
        return status.get("quality_gates", {
            "run_security_review": True,
            "run_qa_review": True,
            "run_tests": True
        })

    def set_quality_gates(self, name: str, gates: Dict[str, bool]) -> Dict[str, Any]:
        """Update per-project quality gates in STATUS.json."""
        project_path = os.path.join(self.projects_dir, name)
        status_file = os.path.join(project_path, "STATUS.json")

        current = self.get_workflow_status(name)
        current["quality_gates"] = {
            "run_security_review": bool(gates.get("run_security_review", True)),
            "run_qa_review": bool(gates.get("run_qa_review", True)),
            "run_tests": bool(gates.get("run_tests", True))
        }

        with open(status_file, 'w') as f:
            json.dump(current, f, indent=2)

        return {"status": "success", "quality_gates": current["quality_gates"]}

    def add_review_issues_to_todo(
        self,
        name: str,
        issues: List[Dict[str, str]],
        review_type: str = "QA"
    ) -> Dict[str, Any]:
        """
        Add issues found during review back to TODO.md.

        Args:
            name: Project name
            issues: List of issues with 'title' and 'description' keys
            review_type: Type of review (QA or Security)

        Returns:
            Dict with status of the operation
        """
        project_path = os.path.join(self.projects_dir, name)
        todo_path = os.path.join(project_path, "TODO.md")

        if not os.path.exists(todo_path):
            return {"status": "error", "message": "TODO.md not found"}

        with open(todo_path, 'r') as f:
            todo_content = f.read()

        # Create new section for review issues
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_section = f"\n\n## {review_type} Issues ({timestamp})\n"

        for issue in issues:
            title = issue.get("title", "Untitled Issue")
            description = issue.get("description", "")
            new_section += f"- [ ] {title}"
            if description:
                new_section += f"\n  - {description}"
            new_section += "\n"

        # Append to TODO.md
        with open(todo_path, 'a') as f:
            f.write(new_section)

        return {
            "status": "success",
            "message": f"Added {len(issues)} {review_type} issues to TODO.md",
            "issues_added": len(issues)
        }

    def append_qa_notes(
        self,
        name: str,
        notes: str,
        section: str = "QA Review Notes",
        agent: str = "unknown"
    ) -> Dict[str, Any]:
        """
        Append notes to the QA notes.md file.

        Args:
            name: Project name
            notes: The notes to append
            section: Which section to append to
            agent: The agent adding the notes

        Returns:
            Dict with status of the operation
        """
        project_path = os.path.join(self.projects_dir, name)
        notes_path = os.path.join(project_path, "QA", "notes.md")

        # Ensure QA directory exists
        qa_dir = os.path.join(project_path, "QA")
        os.makedirs(qa_dir, exist_ok=True)

        # Create notes file if it doesn't exist
        if not os.path.exists(notes_path):
            with open(notes_path, 'w') as f:
                f.write(f"# QA Notes - {name}\n\n## Security Review Notes\n\n## QA Review Notes\n\n")

        # Read current content
        with open(notes_path, 'r') as f:
            content = f.read()

        # Format the new note
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_note = f"\n### [{timestamp}] - {agent}\n{notes}\n"

        # Find the section and append
        section_marker = f"## {section}"
        if section_marker in content:
            # Find the next section or end of file
            section_start = content.index(section_marker) + len(section_marker)
            next_section = content.find("\n## ", section_start)

            if next_section == -1:
                # Append at end
                content = content + formatted_note
            else:
                # Insert before next section
                content = content[:next_section] + formatted_note + content[next_section:]
        else:
            # Section not found, append at end
            content = content + f"\n{section_marker}\n{formatted_note}"

        with open(notes_path, 'w') as f:
            f.write(content)

        return {"status": "success", "message": "Notes appended"}
