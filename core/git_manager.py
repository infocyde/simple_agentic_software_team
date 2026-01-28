"""Git Manager - Handles Git operations for projects."""

import os
import subprocess
from typing import Dict, Any, List, Optional
from datetime import datetime


class GitManager:
    """
    Manages Git operations for a project.
    Human handles final push to remote - agents work locally.
    """

    def __init__(self, project_path: str):
        self.project_path = project_path

    def _run_git(self, *args) -> Dict[str, Any]:
        """Run a git command and return the result."""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Command timed out",
                "returncode": -1
            }
        except FileNotFoundError:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Git not found",
                "returncode": -1
            }

    def is_git_repo(self) -> bool:
        """Check if the project is a git repository."""
        return os.path.exists(os.path.join(self.project_path, ".git"))

    def init(self) -> Dict[str, Any]:
        """Initialize a git repository."""
        if self.is_git_repo():
            return {"success": True, "message": "Already a git repository"}

        result = self._run_git("init")
        if result["success"]:
            # Create initial commit
            self._run_git("add", ".")
            self._run_git("commit", "-m", "Initial commit")
        return result

    def status(self) -> Dict[str, Any]:
        """Get the git status."""
        result = self._run_git("status", "--porcelain")
        if result["success"]:
            lines = result["stdout"].split("\n") if result["stdout"] else []
            files = []
            for line in lines:
                if line.strip():
                    status = line[:2]
                    filename = line[3:]
                    files.append({
                        "status": status.strip(),
                        "file": filename
                    })
            return {
                "success": True,
                "files": files,
                "clean": len(files) == 0
            }
        return result

    def add(self, files: Optional[List[str]] = None) -> Dict[str, Any]:
        """Stage files for commit."""
        if files:
            result = self._run_git("add", *files)
        else:
            result = self._run_git("add", ".")
        return result

    def commit(self, message: str) -> Dict[str, Any]:
        """Create a commit with the given message."""
        # First add all changes
        self.add()

        # Check if there's anything to commit
        status = self.status()
        if status.get("clean", True):
            return {"success": False, "message": "Nothing to commit"}

        # Create the commit
        result = self._run_git("commit", "-m", message)
        return result

    def log(self, limit: int = 10) -> Dict[str, Any]:
        """Get recent commit history."""
        result = self._run_git(
            "log",
            f"-{limit}",
            "--pretty=format:%h|%s|%an|%ai"
        )
        if result["success"]:
            commits = []
            for line in result["stdout"].split("\n"):
                if line.strip():
                    parts = line.split("|")
                    if len(parts) >= 4:
                        commits.append({
                            "hash": parts[0],
                            "message": parts[1],
                            "author": parts[2],
                            "date": parts[3]
                        })
            return {"success": True, "commits": commits}
        return result

    def diff(self, staged: bool = False) -> Dict[str, Any]:
        """Get the current diff."""
        if staged:
            result = self._run_git("diff", "--staged")
        else:
            result = self._run_git("diff")
        return result

    def branch(self) -> Dict[str, Any]:
        """Get the current branch name."""
        result = self._run_git("branch", "--show-current")
        if result["success"]:
            return {"success": True, "branch": result["stdout"]}
        return result

    def create_branch(self, name: str) -> Dict[str, Any]:
        """Create and switch to a new branch."""
        result = self._run_git("checkout", "-b", name)
        return result

    def checkout(self, branch: str) -> Dict[str, Any]:
        """Switch to a branch."""
        result = self._run_git("checkout", branch)
        return result

    def stash(self) -> Dict[str, Any]:
        """Stash current changes."""
        result = self._run_git("stash")
        return result

    def stash_pop(self) -> Dict[str, Any]:
        """Pop stashed changes."""
        result = self._run_git("stash", "pop")
        return result

    def get_summary_for_report(self) -> Dict[str, Any]:
        """Get a summary of git activity for the project report."""
        summary = {
            "is_git_repo": self.is_git_repo()
        }

        if not summary["is_git_repo"]:
            return summary

        # Get branch
        branch_result = self.branch()
        if branch_result["success"]:
            summary["current_branch"] = branch_result["branch"]

        # Get status
        status_result = self.status()
        if status_result["success"]:
            summary["uncommitted_changes"] = len(status_result.get("files", []))
            summary["is_clean"] = status_result.get("clean", True)

        # Get recent commits
        log_result = self.log(5)
        if log_result["success"]:
            summary["recent_commits"] = log_result.get("commits", [])

        return summary
