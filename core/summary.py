"""Summary Generator - Creates completion reports for projects."""

import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from .git_manager import GitManager
from .memory import MemoryManager


class SummaryGenerator:
    """
    Generates completion summary reports for projects.
    Includes: what was built, decisions, issues, lessons learned, deployment instructions.
    """

    def __init__(self, project_path: str):
        self.project_path = project_path
        self.git = GitManager(project_path)
        self.memory = MemoryManager(project_path)

    def generate_summary(
        self,
        what_was_built: str,
        decisions: List[str] = None,
        issues: List[str] = None,
        lessons: List[str] = None,
        deployment_instructions: str = None
    ) -> str:
        """Generate a complete summary report."""

        # Get project name from path
        project_name = os.path.basename(self.project_path)

        # Get git summary
        git_summary = self.git.get_summary_for_report()

        # Build the report
        report = f"""# Project Summary: {project_name}

Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}

## What Was Built

{what_was_built}

## Key Decisions

"""
        if decisions:
            for decision in decisions:
                report += f"- {decision}\n"
        else:
            report += "- No major decisions recorded\n"

        report += """
## Known Issues / Considerations

"""
        if issues:
            for issue in issues:
                report += f"- {issue}\n"
        else:
            report += "- No known issues\n"

        report += """
## Lessons Learned

"""
        if lessons:
            for lesson in lessons:
                report += f"- {lesson}\n"
        else:
            report += "- No lessons recorded\n"

        report += """
## Deployment Instructions

"""
        if deployment_instructions:
            report += deployment_instructions
        else:
            report += self._generate_default_deployment_instructions()

        report += """

## Git Status

"""
        if git_summary.get("is_git_repo"):
            report += f"- Branch: {git_summary.get('current_branch', 'unknown')}\n"
            report += f"- Uncommitted changes: {git_summary.get('uncommitted_changes', 0)}\n"

            if git_summary.get("recent_commits"):
                report += "\n### Recent Commits\n\n"
                for commit in git_summary["recent_commits"][:5]:
                    report += f"- `{commit['hash']}` {commit['message']}\n"
        else:
            report += "- Not a git repository\n"

        report += """

## Project Files

"""
        report += self._list_project_files()

        return report

    def _generate_default_deployment_instructions(self) -> str:
        """Generate default deployment instructions based on project contents."""
        instructions = []

        # Check for common project types
        if os.path.exists(os.path.join(self.project_path, "package.json")):
            instructions.append("""### Node.js Project

```bash
# Install dependencies
npm install

# Run the project
npm start
```
""")

        if os.path.exists(os.path.join(self.project_path, "requirements.txt")):
            instructions.append("""### Python Project

```bash
# Create virtual environment (optional)
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate

# Install dependencies
pip install -r requirements.txt

# Run the project
python main.py  # or appropriate entry point
```
""")

        if os.path.exists(os.path.join(self.project_path, "Cargo.toml")):
            instructions.append("""### Rust Project

```bash
# Build and run
cargo run
```
""")

        if os.path.exists(os.path.join(self.project_path, "go.mod")):
            instructions.append("""### Go Project

```bash
# Run the project
go run .
```
""")

        if os.path.exists(os.path.join(self.project_path, "index.html")):
            instructions.append("""### Static Website

Open `index.html` in a browser, or serve with:

```bash
# Python
python -m http.server 8000

# Node.js (if http-server installed)
npx http-server
```
""")

        if not instructions:
            instructions.append("""### Generic Instructions

Review the project structure and run the appropriate entry point for your project type.
Check SPEC.md for project-specific details.
""")

        return "\n".join(instructions)

    def _list_project_files(self) -> str:
        """Generate a tree-like listing of project files."""
        file_list = []

        for root, dirs, files in os.walk(self.project_path):
            # Skip hidden directories and common ignore patterns
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in [
                'node_modules', '__pycache__', 'venv', '.venv', 'dist', 'build'
            ]]

            level = root.replace(self.project_path, '').count(os.sep)
            indent = '  ' * level
            folder_name = os.path.basename(root)

            if level == 0:
                file_list.append(f"```")
                file_list.append(f"{folder_name}/")
            else:
                file_list.append(f"{indent}{folder_name}/")

            sub_indent = '  ' * (level + 1)
            for file in sorted(files):
                if not file.startswith('.'):
                    file_list.append(f"{sub_indent}{file}")

        file_list.append("```")
        return '\n'.join(file_list)

    def save_summary(self, summary: str) -> str:
        """Save the summary to SUMMARY.md."""
        summary_path = os.path.join(self.project_path, "SUMMARY.md")
        with open(summary_path, 'w') as f:
            f.write(summary)
        return summary_path

    def generate_and_save(
        self,
        what_was_built: str,
        decisions: List[str] = None,
        issues: List[str] = None,
        lessons: List[str] = None,
        deployment_instructions: str = None
    ) -> Dict[str, Any]:
        """Generate and save the summary report."""
        summary = self.generate_summary(
            what_was_built=what_was_built,
            decisions=decisions,
            issues=issues,
            lessons=lessons,
            deployment_instructions=deployment_instructions
        )

        path = self.save_summary(summary)

        return {
            "success": True,
            "path": path,
            "summary": summary
        }
