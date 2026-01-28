"""Project Manager - Handles project creation and management."""

import os
import json
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional


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

    def create_project(self, name: str, init_git: bool = True) -> Dict[str, Any]:
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
        self._create_initial_files(project_path, name)

        # Initialize git if requested
        if init_git:
            self._init_git(project_path)

        return {
            "status": "success",
            "message": f"Project '{name}' created",
            "path": project_path,
            "name": safe_name
        }

    def _create_initial_files(self, project_path: str, display_name: str):
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
        }

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
