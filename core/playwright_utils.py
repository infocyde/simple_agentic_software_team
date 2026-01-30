"""Playwright utilities for QA testing and browser automation."""

import os
import json
import subprocess
import shutil
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path


class PlaywrightManager:
    """
    Manages Playwright detection and configuration for QA testing.
    Supports auto-detection of Playwright MCP server in Claude CLI.
    """

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize the Playwright manager.

        Args:
            config: Configuration dict with playwright settings
        """
        self.config = config or {}
        self.playwright_config = self.config.get("playwright", {})
        self._availability_cache: Optional[bool] = None

    def is_enabled(self) -> bool:
        """Check if Playwright is enabled in configuration."""
        return self.playwright_config.get("enabled", True)

    def should_auto_detect(self) -> bool:
        """Check if auto-detection is enabled."""
        return self.playwright_config.get("auto_detect", True)

    def is_available(self, force_check: bool = False) -> bool:
        """
        Check if Playwright is available for use.

        Args:
            force_check: Force re-check even if cached

        Returns:
            True if Playwright is available and enabled
        """
        if not self.is_enabled():
            return False

        if self._availability_cache is not None and not force_check:
            return self._availability_cache

        if self.should_auto_detect():
            self._availability_cache = self._detect_playwright()
        else:
            # If auto-detect is off, assume it's available if enabled
            self._availability_cache = True

        return self._availability_cache

    def _detect_playwright(self) -> bool:
        """
        Detect if Playwright MCP server is available in Claude CLI.

        Checks:
        1. Claude CLI MCP configuration for playwright server
        2. Playwright npm package installation
        3. Environment variables for Playwright config

        Returns:
            True if Playwright is detected and available
        """
        # Check 1: Look for Claude CLI MCP config
        if self._check_claude_mcp_config():
            return True

        # Check 2: Check if playwright is installed via npm
        if self._check_npm_playwright():
            return True

        # Check 3: Check environment variable
        if os.environ.get("PLAYWRIGHT_AVAILABLE", "").lower() == "true":
            return True

        return False

    def _check_claude_mcp_config(self) -> bool:
        """Check Claude CLI configuration for Playwright MCP server."""
        # Check standalone MCP config files
        config_paths = [
            Path.home() / ".claude" / "mcp_servers.json",
            Path.home() / ".config" / "claude" / "mcp_servers.json",
            Path(os.environ.get("APPDATA", "")) / "claude" / "mcp_servers.json",
        ]

        for config_path in config_paths:
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        mcp_config = json.load(f)

                    # Check for playwright in server names
                    servers = mcp_config.get("servers", mcp_config)
                    if isinstance(servers, dict):
                        for server_name in servers.keys():
                            if "playwright" in server_name.lower():
                                return True
                except (json.JSONDecodeError, IOError):
                    continue

        # Check .claude.json which stores mcpServers inline
        claude_json_path = Path.home() / ".claude.json"
        if claude_json_path.exists():
            try:
                with open(claude_json_path, 'r') as f:
                    claude_config = json.load(f)

                servers = claude_config.get("mcpServers", {})
                if isinstance(servers, dict):
                    for server_name in servers.keys():
                        if "playwright" in server_name.lower():
                            return True
            except (json.JSONDecodeError, IOError):
                pass

        return False

    def _check_npm_playwright(self) -> bool:
        """Check if Playwright is installed via npm."""
        try:
            result = subprocess.run(
                ["npm", "list", "@anthropic/mcp-server-playwright", "--depth=0"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if "@anthropic/mcp-server-playwright" in result.stdout:
                return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Also check for regular playwright
        try:
            result = subprocess.run(
                ["npm", "list", "playwright", "--depth=0"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if "playwright@" in result.stdout:
                return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return False

    def get_screenshot_path(self, project_path: str, name: str = None) -> str:
        """
        Generate a path for saving a screenshot.

        Args:
            project_path: Path to the project directory
            name: Optional name for the screenshot

        Returns:
            Full path for the screenshot file
        """
        qa_dir = os.path.join(project_path, "QA")
        os.makedirs(qa_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if name:
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            filename = f"screenshot_{timestamp}_{safe_name}.png"
        else:
            filename = f"screenshot_{timestamp}.png"

        return os.path.join(qa_dir, filename)

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current Playwright status and configuration.

        Returns:
            Dict with availability, configuration, and detection info
        """
        return {
            "enabled": self.is_enabled(),
            "auto_detect": self.should_auto_detect(),
            "available": self.is_available(),
            "config": {
                "screenshot_dir": self.playwright_config.get("screenshot_dir", "QA"),
                "default_timeout": self.playwright_config.get("default_timeout", 30000),
                "browser": self.playwright_config.get("browser", "chromium")
            }
        }

    def get_qa_instructions(self, spec_summary: str = "") -> str:
        """
        Generate Playwright-specific instructions for QA agent.

        Args:
            spec_summary: Summary of the project spec for context

        Returns:
            Instructions string for the QA agent
        """
        if not self.is_available():
            return """
Playwright is not available. Perform manual testing by:
1. Running the application
2. Testing functionality via CLI or API calls
3. Documenting test results in the QA notes
"""

        return f"""
Playwright is available for browser-based testing. Use it to:

1. **Navigate to the application** - Open the app URL in the browser
2. **Take screenshots** - Capture visual evidence of functionality
3. **Interact with UI elements** - Click buttons, fill forms, etc.
4. **Verify visual appearance** - Check layouts, styling, responsiveness
5. **Test user flows** - Complete end-to-end scenarios

Screenshot naming convention: screenshot_[timestamp]_[test_name].png
Save all screenshots to the project's QA folder.

When testing, verify against these requirements:
{spec_summary}

Always document:
- What was tested
- Expected vs actual results
- Screenshot filenames for reference
"""


def get_default_playwright_config() -> Dict[str, Any]:
    """
    Get the default Playwright configuration.

    Returns:
        Default configuration dict for playwright settings
    """
    return {
        "enabled": True,
        "auto_detect": True,
        "screenshot_dir": "QA",
        "default_timeout": 30000,
        "browser": "chromium",
        "headless": False,
        "viewport": {
            "width": 1280,
            "height": 720
        }
    }
