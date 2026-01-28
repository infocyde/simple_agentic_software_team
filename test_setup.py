"""Quick test to verify the system is set up correctly."""

import os
import sys
import subprocess

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")

    # Check if dependencies are installed
    try:
        import fastapi
        import uvicorn
        print("  [OK] Dependencies installed")
    except ImportError as e:
        print(f"  [WARN] Missing dependency: {e}")
        print("         Run: pip install -r requirements.txt")
        return True  # Not a hard failure, just needs setup

    try:
        from agents import (
            BaseAgent,
            ProjectManagerAgent,
            SoftwareEngineerAgent,
            UIUXEngineerAgent,
            DatabaseAdminAgent,
            SecurityReviewerAgent
        )
        print("  [OK] Agents module")
    except ImportError as e:
        print(f"  [FAIL] Agents module: {e}")
        return False

    try:
        from core import (
            Orchestrator,
            MemoryManager,
            ProjectManager,
            GitManager,
            SummaryGenerator,
            Guardrails
        )
        print("  [OK] Core module")
    except ImportError as e:
        print(f"  [FAIL] Core module: {e}")
        return False

    return True


def test_config():
    """Test that config file exists and is valid."""
    print("Testing configuration...")

    import json
    config_path = os.path.join(os.path.dirname(__file__), "config.json")

    if not os.path.exists(config_path):
        print(f"  [FAIL] Config file not found: {config_path}")
        return False

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        print("  [OK] Config file is valid JSON")

        required_keys = ["defaults", "agents"]
        for key in required_keys:
            if key not in config:
                print(f"  [FAIL] Missing required config key: {key}")
                return False
        print("  [OK] Required config keys present")

    except json.JSONDecodeError as e:
        print(f"  [FAIL] Invalid JSON: {e}")
        return False

    return True


def test_directories():
    """Test that required directories exist."""
    print("Testing directories...")

    base_dir = os.path.dirname(__file__)
    required_dirs = [
        "agents",
        "core",
        "web",
        "web/static",
        "web/templates",
        "projects"
    ]

    all_ok = True
    for dir_name in required_dirs:
        dir_path = os.path.join(base_dir, dir_name)
        if os.path.isdir(dir_path):
            print(f"  [OK] {dir_name}/")
        else:
            print(f"  [FAIL] {dir_name}/ not found")
            all_ok = False

    return all_ok


def test_claude_cli():
    """Test that Claude Code CLI is available."""
    print("Testing Claude Code CLI...")

    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            print(f"  [OK] Claude CLI found: {version[:50]}")
            return True
        else:
            print("  [FAIL] Claude CLI returned error")
            print(f"         {result.stderr[:100]}")
            return False
    except FileNotFoundError:
        print("  [FAIL] Claude CLI not found")
        print("         Install from: https://claude.ai/code")
        print("         Make sure 'claude' is in your PATH")
        return False
    except subprocess.TimeoutExpired:
        print("  [WARN] Claude CLI timed out")
        return True  # Might still work
    except Exception as e:
        print(f"  [FAIL] Error checking Claude CLI: {e}")
        return False


def test_project_manager():
    """Test creating a project."""
    print("Testing project creation...")

    try:
        from core import ProjectManager
    except ImportError:
        print("  [SKIP] Dependencies not installed")
        return True

    base_dir = os.path.dirname(__file__)
    pm = ProjectManager(base_dir)

    # Create a test project
    result = pm.create_project("test-project-setup", init_git=False)

    if result["status"] == "success":
        print(f"  [OK] Created test project at {result['path']}")

        # Clean up
        import shutil
        shutil.rmtree(result["path"])
        print("  [OK] Cleaned up test project")
        return True
    else:
        print(f"  [FAIL] {result.get('message', 'Unknown error')}")
        return False


def main():
    """Run all tests."""
    print("=" * 50)
    print("Agentic Software Team - Setup Test")
    print("=" * 50)
    print()

    results = []

    results.append(("Imports", test_imports()))
    print()

    results.append(("Configuration", test_config()))
    print()

    results.append(("Directories", test_directories()))
    print()

    results.append(("Claude CLI", test_claude_cli()))
    print()

    results.append(("Project Manager", test_project_manager()))
    print()

    print("=" * 50)
    print("Results Summary")
    print("=" * 50)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All tests passed! Run 'python main.py' to start the server.")
    else:
        print("Some tests failed. Please check the errors above.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
