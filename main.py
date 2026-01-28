"""Main entry point for the Agentic Software Team."""

import os
import json
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from core.orchestrator import Orchestrator
from core.project import ProjectManager

# Load environment variables
load_dotenv()

# Get the base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Global state
active_orchestrators: Dict[str, Orchestrator] = {}
websocket_connections: List[WebSocket] = []
project_manager = ProjectManager(BASE_DIR)

# Load config
config_path = os.path.join(BASE_DIR, "config.json")
with open(config_path, 'r') as f:
    config = json.load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    print("Agentic Software Team starting up...")
    yield
    print("Shutting down...")


app = FastAPI(
    title="Agentic Software Team",
    description="A team of AI agents that build software together",
    lifespan=lifespan
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "web", "templates"))


# Pydantic models for requests
class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None


class MessageRequest(BaseModel):
    project: str
    message: str


class HumanInputResponse(BaseModel):
    project: str
    response: str


# WebSocket connection manager
async def broadcast_activity(activity: Dict[str, Any]):
    """Broadcast activity to all connected WebSocket clients."""
    for websocket in websocket_connections:
        try:
            await websocket.send_json(activity)
        except Exception:
            pass


def create_activity_callback(project_name: str):
    """Create an activity callback for a specific project."""
    def callback(activity: Dict[str, Any]):
        activity["project"] = project_name
        asyncio.create_task(broadcast_activity(activity))
    return callback


def create_human_input_callback(project_name: str):
    """Create a human input callback for a specific project."""
    def callback(request: Dict[str, Any]):
        request["project"] = project_name
        request["type"] = "human_input_needed"
        asyncio.create_task(broadcast_activity(request))
    return callback


# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the main dashboard."""
    projects = project_manager.list_projects()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "projects": projects}
    )


@app.get("/api/projects")
async def list_projects():
    """List all projects."""
    return {"projects": project_manager.list_projects()}


@app.post("/api/projects")
async def create_project(req: CreateProjectRequest):
    """Create a new project."""
    result = project_manager.create_project(req.name)
    if result["status"] == "success":
        # Initialize orchestrator for the new project
        orchestrator = Orchestrator(
            project_path=result["path"],
            config=config,
            activity_callback=create_activity_callback(result["name"]),
            human_input_callback=create_human_input_callback(result["name"])
        )
        active_orchestrators[result["name"]] = orchestrator
    return result


@app.get("/api/projects/{name}")
async def get_project(name: str):
    """Get project details."""
    return project_manager.get_project_status(name)


@app.get("/api/projects/{name}/spec")
async def get_project_spec(name: str):
    """Get project specification."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    spec_path = os.path.join(project_path, "SPEC.md")
    if os.path.exists(spec_path):
        with open(spec_path, 'r') as f:
            return {"spec": f.read()}
    return {"spec": ""}


@app.get("/api/projects/{name}/todo")
async def get_project_todo(name: str):
    """Get project TODO list."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    todo_path = os.path.join(project_path, "TODO.md")
    if os.path.exists(todo_path):
        with open(todo_path, 'r') as f:
            return {"todo": f.read()}
    return {"todo": ""}


@app.get("/api/projects/{name}/activity")
async def get_project_activity(name: str, limit: int = 50):
    """Get recent activity for a project."""
    if name in active_orchestrators:
        return {"activity": active_orchestrators[name].get_activity_log(limit)}
    return {"activity": []}


@app.post("/api/projects/{name}/kickoff")
async def start_kickoff(name: str, req: MessageRequest):
    """Start project kickoff with initial request."""
    if name not in active_orchestrators:
        project_path = project_manager.get_project_path(name)
        if not project_path:
            raise HTTPException(status_code=404, detail="Project not found")

        active_orchestrators[name] = Orchestrator(
            project_path=project_path,
            config=config,
            activity_callback=create_activity_callback(name),
            human_input_callback=create_human_input_callback(name)
        )

    orchestrator = active_orchestrators[name]

    # Run kickoff in background
    asyncio.create_task(orchestrator.start_project_kickoff(req.message))

    return {"status": "started", "message": "Kickoff started"}


@app.post("/api/projects/{name}/feature")
async def start_feature(name: str, req: MessageRequest):
    """Start a new feature request."""
    if name not in active_orchestrators:
        project_path = project_manager.get_project_path(name)
        if not project_path:
            raise HTTPException(status_code=404, detail="Project not found")

        active_orchestrators[name] = Orchestrator(
            project_path=project_path,
            config=config,
            activity_callback=create_activity_callback(name),
            human_input_callback=create_human_input_callback(name)
        )

    orchestrator = active_orchestrators[name]

    # Run feature request in background
    asyncio.create_task(orchestrator.start_feature_request(req.message))

    return {"status": "started", "message": "Feature request started"}


@app.post("/api/projects/{name}/continue")
async def continue_work(name: str):
    """Continue working on the project."""
    if name not in active_orchestrators:
        project_path = project_manager.get_project_path(name)
        if not project_path:
            raise HTTPException(status_code=404, detail="Project not found")

        active_orchestrators[name] = Orchestrator(
            project_path=project_path,
            config=config,
            activity_callback=create_activity_callback(name),
            human_input_callback=create_human_input_callback(name)
        )

    orchestrator = active_orchestrators[name]

    # Continue work in background
    asyncio.create_task(orchestrator.continue_work())

    return {"status": "started", "message": "Continuing work"}


@app.post("/api/projects/{name}/human-input")
async def provide_human_input(name: str, req: HumanInputResponse):
    """Provide human input to a waiting agent."""
    if name not in active_orchestrators:
        raise HTTPException(status_code=404, detail="No active orchestrator for project")

    orchestrator = active_orchestrators[name]
    orchestrator.provide_human_input(req.response)

    return {"status": "received"}


@app.get("/api/config")
async def get_config():
    """Get current configuration."""
    return config


@app.put("/api/config")
async def update_config(new_config: Dict[str, Any]):
    """Update configuration."""
    global config
    config.update(new_config)

    # Save to file
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    return {"status": "updated", "config": config}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time activity updates."""
    await websocket.accept()
    websocket_connections.append(websocket)

    try:
        while True:
            # Keep connection alive and receive any messages
            data = await websocket.receive_text()
            # Could handle incoming messages here if needed
    except WebSocketDisconnect:
        websocket_connections.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
