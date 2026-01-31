"""Project launch utilities for UAT manual testing."""

from __future__ import annotations

import os
import re
import subprocess
import webbrowser
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
from datetime import datetime
import time


_INSTALL_COMMANDS = (
    "pip install",
    "uv pip",
    "uv venv",
    "python -m venv",
    "npm install",
    "pnpm install",
    "yarn install",
    "bun install",
    "dotnet restore",
)

_FRAMEWORK_DEFAULT_PORTS = {
    "uvicorn": 8000,
    "fastapi": 8000,
    "django": 8000,
    "flask": 5000,
    "streamlit": 8501,
    "react-scripts": 3000,
    "next": 3000,
    "ng serve": 4200,
    "vite": 5173,
    "gatsby": 8000,
    "parcel": 1234,
    "aspnetcore": 5000,
}

_BANNED_PORTS = {8000, 8080}
_FALLBACK_PORT = 8001


@dataclass
class LaunchInfo:
    command: str
    launch_url: Optional[str]
    log_path: Optional[str]


class ProjectLauncher:
    """Launch projects for manual testing during UAT."""

    def __init__(self) -> None:
        self._active: Dict[str, subprocess.Popen] = {}
        self._launch_info: Dict[str, LaunchInfo] = {}

    def launch_project(self, project_name: str, project_path: str) -> Dict[str, str]:
        running = self._get_running_process(project_name)
        if running:
            info = self._launch_info.get(project_name)
            return {
                "status": "running",
                "message": "Project already running",
                "command": info.command if info else "",
                "launch_url": info.launch_url if info else "",
                "log_path": info.log_path if info else ""
            }

        command, launch_url = self._get_launch_command(project_path)
        if not command:
            return {
                "status": "error",
                "message": "No launch command found in runit.md. Add an explicit run command block."
            }

        log_path = os.path.join(project_path, "launch.log")
        try:
            log_file = open(log_path, "a", encoding="utf-8")
            log_file.write(f"\n[{datetime.now().isoformat()}] Launch command: {command}\n")
            log_file.write(f"[{datetime.now().isoformat()}] Working dir: {project_path}\n")
            log_file.flush()
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Unable to write launch log: {exc}"
            }

        venv_created = False
        runit_content = self._read_runit_content(project_path)
        if self._is_python_command(command):
            try:
                venv_created = self._ensure_python_venv(project_path, runit_content, log_file)
            except Exception as exc:
                log_file.write(f"[{datetime.now().isoformat()}] Venv setup failed: {exc}\n")
                log_file.flush()
                return {
                    "status": "error",
                    "message": f"Venv setup failed: {exc}"
                }

        env = self._build_launch_env(project_path)
        command, env = self._apply_port_policy(command, env)

        process = subprocess.Popen(
            command,
            cwd=project_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            shell=True,
            creationflags=self._creation_flags()
        )

        self._active[project_name] = process
        info = LaunchInfo(command=command, launch_url=launch_url, log_path=log_path)
        self._launch_info[project_name] = info

        return {
            "status": "started",
            "message": "Launch started",
            "command": command,
            "launch_url": launch_url or "",
            "log_path": log_path,
            "venv_created": venv_created
        }

    def stop_project(self, project_name: str) -> Dict[str, str]:
        process = self._active.get(project_name)
        if not process or process.poll() is not None:
            self._active.pop(project_name, None)
            return {"status": "not_running", "message": "Project is not running"}

        try:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()
        finally:
            self._active.pop(project_name, None)

        return {"status": "stopped", "message": "Project stopped"}

    def get_launch_info(self, project_name: str) -> Optional[LaunchInfo]:
        return self._launch_info.get(project_name)

    def _get_running_process(self, project_name: str) -> Optional[subprocess.Popen]:
        process = self._active.get(project_name)
        if not process:
            return None
        if process.poll() is None:
            return process
        self._active.pop(project_name, None)
        return None

    def _read_runit_content(self, project_path: str) -> str:
        runit_path = os.path.join(project_path, "runit.md")
        if os.path.exists(runit_path):
            with open(runit_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _get_launch_command(self, project_path: str) -> Tuple[Optional[str], Optional[str]]:
        runit_content = self._read_runit_content(project_path)

        command = self._pick_command_from_runit(runit_content)
        if not command:
            command = self._pick_command_from_text(runit_content)
        if not command:
            return None, None

        command = self._apply_venv(command, project_path)
        command = self._maybe_prefix_backend(command, project_path, runit_content)
        launch_url = self._infer_launch_url(runit_content, command)
        return command, launch_url

    def _pick_command_from_runit(self, runit_content: str) -> Optional[str]:
        if not runit_content:
            return None

        blocks = self._extract_code_blocks(runit_content)
        candidates: List[Tuple[int, str]] = []
        for block in blocks:
            for line in self._block_lines(block):
                score = self._score_command(line)
                if score > 0:
                    candidates.append((score, line))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _extract_code_blocks(self, text: str) -> List[str]:
        pattern = re.compile(r"```(?:[a-zA-Z0-9_-]+)?\n(.*?)```", re.S)
        return [match.group(1) for match in pattern.finditer(text)]

    def _block_lines(self, block: str) -> List[str]:
        lines = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("$"):
                line = line[1:].strip()
            lines.append(line)
        return lines

    def _score_command(self, command: str) -> int:
        lowered = command.lower()
        if any(cmd in lowered for cmd in _INSTALL_COMMANDS):
            return -1
        if any(token in lowered for token in ("venv", "activate", "pip install", "docker build", "docker run")):
            return -1

        score = 0
        keywords = [
            "uvicorn",
            "flask",
            "streamlit",
            "django",
            "python",
            "dotnet run",
            "node",
            "npm",
            "pnpm",
            "yarn",
            "bun",
            "react-scripts",
            "next",
            "vite",
            "ng serve",
        ]
        for keyword in keywords:
            if keyword in lowered:
                score += 4
        if "run" in lowered or "start" in lowered or "serve" in lowered:
            score += 1
        return score

    def _pick_command_from_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        candidates: List[Tuple[int, str]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            score = self._score_command(line)
            if score > 0:
                candidates.append((score, line))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _apply_venv(self, command: str, project_path: str) -> str:
        venv_dir = os.path.join(project_path, ".venv")
        if not os.path.isdir(venv_dir):
            return command

        python_path = os.path.join(venv_dir, "Scripts", "python.exe")
        if not os.path.exists(python_path):
            return command
        if not os.access(python_path, os.X_OK):
            return command

        lowered = command.strip().lower()
        if lowered.startswith(("python ", "python3 ", "py ")):
            _, rest = command.split(" ", 1)
            return f"\"{python_path}\" {rest}".strip()

        module_map = {
            "uvicorn": "uvicorn",
            "flask": "flask",
            "streamlit": "streamlit",
            "gunicorn": "gunicorn",
            "django-admin": "django",
        }
        for prefix, module in module_map.items():
            if lowered.startswith(prefix + " "):
                rest = command[len(prefix):].strip()
                return f"\"{python_path}\" -m {module} {rest}".strip()

        return command

    def _ensure_python_venv(self, project_path: str, runit_content: str, log_file) -> bool:
        venv_dir = os.path.join(project_path, ".venv")
        if os.path.isdir(venv_dir):
            return False

        log_file.write(f"[{datetime.now().isoformat()}] .venv missing; creating...\n")
        log_file.flush()
        create_cmd = "python -m venv .venv"
        result = subprocess.run(create_cmd, cwd=project_path, shell=True)
        if result.returncode != 0:
            raise RuntimeError("Failed to create .venv")

        python_path = os.path.join(venv_dir, "Scripts", "python.exe")
        if not os.path.exists(python_path):
            raise RuntimeError("Created .venv but python.exe not found")

        requirements_path = self._find_requirements(project_path, runit_content)
        if requirements_path:
            log_file.write(f"[{datetime.now().isoformat()}] Installing deps: {requirements_path}\n")
            log_file.flush()
            install_cmd = f"\"{python_path}\" -m pip install -r \"{requirements_path}\""
            result = subprocess.run(install_cmd, cwd=os.path.dirname(requirements_path), shell=True)
            if result.returncode != 0:
                raise RuntimeError("Dependency install failed")

        log_file.write(f"[{datetime.now().isoformat()}] .venv ready\n")
        log_file.flush()
        return True

    def _find_requirements(self, project_path: str, runit_content: str) -> Optional[str]:
        backend_path = os.path.join(project_path, "backend", "requirements.txt")
        root_path = os.path.join(project_path, "requirements.txt")
        if "backend" in runit_content.lower() and os.path.exists(backend_path):
            return backend_path
        if os.path.exists(root_path):
            return root_path
        if os.path.exists(backend_path):
            return backend_path
        return None

    def _apply_port_policy(self, command: str, env: Dict[str, str]) -> Tuple[str, Dict[str, str]]:
        command = self._replace_banned_port(command)
        if self._command_has_port(command):
            return command, env

        lowered = command.lower()
        safe_port = _FALLBACK_PORT

        if "uvicorn" in lowered:
            return f"{command} --port {safe_port}", env
        if "flask run" in lowered:
            return f"{command} --port {safe_port}", env
        if "streamlit" in lowered:
            return f"{command} --server.port {safe_port}", env
        if "manage.py runserver" in lowered:
            return f"{command} {safe_port}", env

        if "dotnet run" in lowered:
            env = env.copy()
            env.setdefault("ASPNETCORE_URLS", f"http://localhost:{safe_port}")
            return command, env

        env = env.copy()
        env.setdefault("PORT", str(safe_port))
        return command, env

    def _build_launch_env(self, project_path: str) -> Dict[str, str]:
        env = os.environ.copy()
        venv_dir = os.path.join(project_path, ".venv")
        scripts_dir = os.path.join(venv_dir, "Scripts")
        if os.path.isdir(venv_dir) and os.path.isdir(scripts_dir):
            env["VIRTUAL_ENV"] = venv_dir
            env["PATH"] = scripts_dir + os.pathsep + env.get("PATH", "")
        return env

    def _infer_launch_url(self, runit_content: str, command: str) -> Optional[str]:
        url = self._extract_url(runit_content)
        if url:
            return self._replace_banned_port_in_url(url)

        port = self._extract_port_from_command(command)
        if port:
            if port in _BANNED_PORTS:
                return f"http://localhost:{_FALLBACK_PORT}"
            return f"http://localhost:{port}"

        lowered = command.lower()
        for keyword, default_port in _FRAMEWORK_DEFAULT_PORTS.items():
            if keyword in lowered:
                if default_port in _BANNED_PORTS:
                    return f"http://localhost:{_FALLBACK_PORT}"
                return f"http://localhost:{default_port}"

        return None

    def _extract_url(self, text: str) -> Optional[str]:
        if not text:
            return None
        match = re.search(r"https?://[^\s)]+", text)
        if match:
            return match.group(0).rstrip(".,)")
        match = re.search(r"localhost:\d+", text)
        if match:
            return f"http://{match.group(0)}"
        return None

    def _extract_port_from_command(self, command: str) -> Optional[int]:
        if not command:
            return None
        port_match = re.search(r"--port\s+(\d+)", command)
        if not port_match:
            port_match = re.search(r"-p\s+(\d+)", command)
        if not port_match:
            port_match = re.search(r":(\d{4,5})", command)
        if port_match:
            try:
                return int(port_match.group(1))
            except ValueError:
                return None
        return None

    def _command_has_port(self, command: str) -> bool:
        if not command:
            return False
        return bool(re.search(r"--port\s+\d+|-p\s+\d+|:(\d{4,5})", command))

    def _replace_banned_port(self, command: str) -> str:
        def repl(match: re.Match) -> str:
            port = int(match.group(1))
            if port in _BANNED_PORTS:
                return match.group(0).replace(str(port), str(_FALLBACK_PORT))
            return match.group(0)

        command = re.sub(r"--port\s+(\d+)", repl, command)
        command = re.sub(r"-p\s+(\d+)", repl, command)
        command = re.sub(r":(\d{4,5})", repl, command)
        return command

    def _replace_banned_port_in_url(self, url: str) -> str:
        match = re.search(r":(\d{4,5})", url)
        if not match:
            return url
        try:
            port = int(match.group(1))
        except ValueError:
            return url
        if port in _BANNED_PORTS:
            return url.replace(f":{port}", f":{_FALLBACK_PORT}")
        return url

    def _maybe_prefix_backend(self, command: str, project_path: str, runit_content: str) -> str:
        lowered = command.lower()
        if lowered.startswith("cd "):
            return command
        if "backend" not in runit_content.lower():
            return command
        backend_path = os.path.join(project_path, "backend")
        if not os.path.isdir(backend_path):
            return command
        backend_main = os.path.join(backend_path, "main.py")
        backend_app = os.path.join(backend_path, "app.py")
        if os.path.exists(backend_main) or os.path.exists(backend_app):
            return f"cd backend && {command}"
        return command

    def _is_python_command(self, command: str) -> bool:
        lowered = command.lower()
        tokens = ("python", "uvicorn", "flask", "streamlit", "django", "gunicorn")
        return any(token in lowered for token in tokens)

    def _creation_flags(self) -> int:
        if os.name != "nt":
            return 0
        flags = 0
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS
        return flags
