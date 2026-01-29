# Future Feature: Project Launch Button

## Overview

Add a "Launch" button to the web interface that starts and runs projects created by the agent team, allowing users to demo/preview their work directly from the UI.

---

## Current State

### Existing Projects Types
- **Static HTML** (e.g., `helloworld`) - Simple HTML/CSS/JS files
- **React/Vite** (e.g., `simple_ai_art_gallery`) - Node.js build pipeline

### No Current Launch Mechanism
- No endpoint to execute/preview projects
- No process management for spawned servers
- No port allocation system
- No output capture/streaming for running processes

---

## Proposed Implementation

### 1. Project Type Detection

Create detection logic to identify project types:

```python
def detect_project_type(project_path):
    # Check for React/Node.js
    if os.path.exists(os.path.join(project_path, "package.json")):
        return "node"

    # Check for Python backend
    if os.path.exists(os.path.join(project_path, "requirements.txt")):
        return "python"

    # Check for Docker
    if os.path.exists(os.path.join(project_path, "Dockerfile")):
        return "docker"

    # Default to static
    if os.path.exists(os.path.join(project_path, "index.html")):
        return "static"

    return None
```

### 2. Launch Commands by Type

| Project Type | Detection | Launch Command |
|--------------|-----------|----------------|
| Static HTML | `index.html` exists | `python -m http.server {port} --directory {path}` |
| Node/React | `package.json` exists | `npm install && npm run dev` |
| Python backend | `requirements.txt` + `main.py`/`app.py` | `pip install -r requirements.txt && python main.py` |
| Docker | `Dockerfile` exists | `docker build -t {name} . && docker run -p {port}:80 {name}` |

### 3. Full-Stack Project Support

For projects with both frontend and backend:

1. **Detect backend presence:**
   - `main.py` or `app.py` → Python backend (Flask/FastAPI)
   - `server.js` or `backend/` folder → Node backend

2. **Start multiple processes:**
   - Backend on one port (e.g., 8001)
   - Frontend on another port (e.g., 5173 for Vite)
   - Track both processes per project

3. **Handle dependencies:**
   - Backend: `pip install -r requirements.txt`
   - Frontend: `npm install`
   - Start backend first if frontend depends on API

---

## New Files to Create

### `core/project_launcher.py`

```python
class ProjectLauncher:
    def __init__(self, base_port=8001):
        self.base_port = base_port
        self.running_processes = {}  # {project_name: [ProcessInfo]}
        self.port_allocations = {}   # {project_name: [ports]}

    async def find_available_port(self, start_port=None):
        """Find next available port starting from base_port"""
        pass

    def detect_project_type(self, project_path):
        """Detect project type based on files present"""
        pass

    def get_launch_commands(self, project_path, project_type, port):
        """Get list of commands to launch project"""
        pass

    async def launch_project(self, project_name, project_path):
        """Launch project and return server URL(s)"""
        pass

    async def stop_project(self, project_name):
        """Stop all processes for a project"""
        pass

    async def stream_output(self, project_name, process):
        """Stream process output to WebSocket"""
        pass
```

---

## Files to Modify

### `main.py` - New Endpoints

```python
@app.post("/api/projects/{name}/launch")
async def launch_project(name: str):
    """Launch a project for demo/preview"""
    pass

@app.post("/api/projects/{name}/stop")
async def stop_project(name: str):
    """Stop a running project"""
    pass

@app.get("/api/projects/{name}/server-info")
async def get_server_info(name: str):
    """Get running server info for a project"""
    pass
```

### `web/templates/index.html` - Launch Button

Add to project header (near "Start Work" button):
```html
<button id="launchBtn" class="btn btn-success" onclick="app.launchProject()">
    Launch
</button>
```

Add launch status modal/panel for:
- Server URL with "Open in Browser" link
- Real-time output/logs
- Stop/Restart buttons

### `web/static/app.js` - Frontend Logic

```javascript
async launchProject() {
    // Call launch endpoint
    // Show loading state
    // Handle WebSocket messages for status
}

// WebSocket message handlers
handleLaunchStarted(data) { }
handleLaunchOutput(data) { }
handleLaunchComplete(data) { }
handleLaunchError(data) { }
```

### `config.json` - Launch Configuration

```json
{
  "project_launch": {
    "base_port": 8001,
    "max_port_attempts": 100,
    "enable_launch": true,
    "process_timeout": 3600,
    "allowed_project_types": ["static", "node", "python", "docker"]
  }
}
```

---

## WebSocket Messages

```javascript
// Server → Client
{ "type": "launch_started", "project": "name", "message": "Starting..." }
{ "type": "launch_output", "project": "name", "output": "...", "stream": "stdout|stderr" }
{ "type": "launch_complete", "project": "name", "server_url": "http://localhost:8001", "ports": [8001] }
{ "type": "launch_error", "project": "name", "error": "Port already in use" }
{ "type": "launch_stopped", "project": "name" }
```

---

## Port Management

- Base port: 8001 (avoid conflict with main app on 8000)
- Scan for available ports up to base_port + 100
- Track allocations per project
- Release ports on stop/error
- Handle Windows vs Linux differences

---

## Security Considerations

1. **Execution Context:**
   - Projects run in their own directory
   - Validate project has SPEC.md before allowing launch
   - Use localhost only (no external access)

2. **Resource Limits:**
   - Process timeout (prevent runaway servers)
   - Max concurrent launched projects
   - Memory/CPU monitoring (optional)

3. **User Intent:**
   - Only launch after explicit button click
   - Clear visual feedback during execution
   - Easy stop/cleanup

---

## Implementation Phases

### Phase 1: Core Infrastructure
- Create `core/project_launcher.py`
- Add `/api/projects/{name}/launch` endpoint
- Implement port allocation logic
- Basic process spawning for static projects

### Phase 2: Frontend Integration
- Add "Launch" button to project header
- Create launch status modal/panel
- Add WebSocket handling for launch events
- "Open in Browser" link

### Phase 3: Multi-Type Support
- Node/React project detection and launching
- Python backend detection and launching
- Full-stack projects (multiple processes)
- Dependency installation handling

### Phase 4: Polish & Error Handling
- Graceful shutdown on app exit
- Process cleanup on errors
- User-friendly error messages
- Output streaming optimization
- Docker support (optional)

---

## Estimated Complexity

| Component | Complexity |
|-----------|------------|
| Frontend button + modal | Low |
| Basic endpoints | Low |
| Project type detection | Low |
| Process launcher service | Medium |
| Port management | Low-Medium |
| WebSocket streaming | Medium |
| Multi-process (full-stack) | Medium |
| Error handling/cleanup | Medium |
| **Overall** | **Medium** |

---

## Dependencies

- No new Python packages required (uses asyncio, subprocess)
- Frontend uses existing WebSocket infrastructure
- Projects need their own dependencies installed (npm, pip)

---

## Open Questions

1. Should `npm install` / `pip install` run automatically before launch, or as a separate "Setup" step?
2. Should launched projects persist across app restarts?
3. Max number of concurrent launched projects?
4. Should there be a "Build" step for production builds vs dev servers?

## Notes

- The current workflow uses statuses: WIP → Security Review → QA → UAT → Done.
- If a launch feature is added, consider whether launching is allowed before UAT approval.
