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
from core.project import ProjectManager, ProjectStatus
from core.conversation import ConversationManager
from core.playwright_utils import PlaywrightManager

# Load environment variables
load_dotenv()

# Get the base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Global state
active_orchestrators: Dict[str, Orchestrator] = {}
active_conversations: Dict[str, ConversationManager] = {}
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
    print(f"Open http://localhost:8000 in your browser")
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
    message: str


class ChatRequest(BaseModel):
    message: str


class StatusUpdateRequest(BaseModel):
    status: str
    reason: Optional[str] = "Manual status update"


# WebSocket connection manager
async def broadcast_message(message: Dict[str, Any]):
    """Broadcast a message to all connected WebSocket clients."""
    disconnected = []
    for websocket in websocket_connections:
        try:
            await websocket.send_json(message)
        except Exception:
            disconnected.append(websocket)

    # Clean up disconnected sockets
    for ws in disconnected:
        if ws in websocket_connections:
            websocket_connections.remove(ws)


def create_activity_callback(project_name: str):
    """Create an activity callback for a specific project."""
    def callback(activity: Dict[str, Any]):
        activity["project"] = project_name
        activity["type"] = "activity"
        asyncio.create_task(broadcast_message(activity))
    return callback


async def create_message_callback(project_name: str):
    """Create a message callback for conversation manager."""
    async def callback(message: Dict[str, Any]):
        message["project"] = project_name
        await broadcast_message(message)
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
        with open(spec_path, 'r', encoding='utf-8') as f:
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
        with open(todo_path, 'r', encoding='utf-8') as f:
            return {"todo": f.read()}
    return {"todo": ""}


@app.get("/api/projects/{name}/activity")
async def get_project_activity(name: str, limit: int = 50):
    """Get recent activity for a project."""
    if name in active_orchestrators:
        return {"activity": active_orchestrators[name].get_activity_log(limit)}
    return {"activity": []}


@app.get("/api/projects/{name}/summary")
async def get_project_summary(name: str):
    """Get project summary (generated on completion)."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    summary_path = os.path.join(project_path, "SUMMARY.md")
    if os.path.exists(summary_path):
        with open(summary_path, 'r', encoding='utf-8') as f:
            return {"summary": f.read()}
    return {"summary": ""}


@app.post("/api/projects/{name}/kickoff")
async def start_kickoff(name: str, req: MessageRequest):
    """Start project kickoff with interactive Q&A."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    # Create message callback
    async def message_callback(message: Dict[str, Any]):
        message["project"] = name
        await broadcast_message(message)

    # Create conversation manager
    conversation = ConversationManager(
        project_path=project_path,
        message_callback=message_callback,
        activity_callback=create_activity_callback(name)
    )

    active_conversations[name] = conversation

    # Get number of questions from config
    num_questions = config.get("project_kickoff_questions", 18)

    # Start kickoff conversation in background
    asyncio.create_task(conversation.start_kickoff_conversation(req.message, num_questions))

    return {"status": "started", "message": "Kickoff conversation started"}


@app.post("/api/projects/{name}/feature")
async def start_feature(name: str, req: MessageRequest):
    """Start a feature request with interactive Q&A."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    # Create message callback
    async def message_callback(message: Dict[str, Any]):
        message["project"] = name
        await broadcast_message(message)

    # Create conversation manager
    conversation = ConversationManager(
        project_path=project_path,
        message_callback=message_callback,
        activity_callback=create_activity_callback(name)
    )

    active_conversations[name] = conversation

    # Get number of questions from config
    num_questions = config.get("feature_kickoff_questions", 10)

    # Start feature conversation in background
    asyncio.create_task(conversation.start_feature_conversation(req.message, num_questions))

    return {"status": "started", "message": "Feature conversation started"}


@app.post("/api/projects/{name}/chat")
async def send_chat_message(name: str, req: ChatRequest):
    """Send a chat message to the active conversation."""
    if name not in active_conversations:
        raise HTTPException(status_code=404, detail="No active conversation for project")

    conversation = active_conversations[name]

    if not conversation.is_active:
        raise HTTPException(status_code=400, detail="Conversation is not active")

    # Pass the user's message to the conversation
    conversation.receive_user_input(req.message)

    return {"status": "received"}


@app.post("/api/projects/{name}/write-spec")
async def write_spec(name: str):
    """Trigger spec and todo creation from current conversation."""
    if name not in active_conversations:
        raise HTTPException(status_code=404, detail="No active conversation for project")

    conversation = active_conversations[name]

    if not conversation.is_active:
        raise HTTPException(status_code=400, detail="Conversation is not active")

    # Signal to create the spec
    conversation.trigger_spec_creation()

    return {"status": "triggered", "message": "Creating spec and todo documents..."}


@app.post("/api/projects/{name}/uat")
async def start_uat(name: str):
    """Start UAT (User Acceptance Testing) conversation."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check that project is in UAT status
    workflow_status = project_manager.get_workflow_status(name)
    current_status = workflow_status.get("current_status", "")
    if current_status != "uat":
        raise HTTPException(
            status_code=400,
            detail=f"Project must be in UAT status to start UAT. Current status: {current_status}"
        )

    # Create message callback
    async def message_callback(message: Dict[str, Any]):
        message["project"] = name
        await broadcast_message(message)

    # Create status callback for UAT completion
    async def status_callback(new_status: str, reason: str):
        status_enum = ProjectStatus.from_string(new_status)
        project_manager.set_workflow_status(
            name=name,
            new_status=status_enum,
            agent="conversation_manager",
            reason=reason
        )
        # Broadcast status change
        await broadcast_message({
            "type": "status_change",
            "project": name,
            "new_status": new_status,
            "reason": reason
        })

    # Create conversation manager
    conversation = ConversationManager(
        project_path=project_path,
        message_callback=message_callback,
        activity_callback=create_activity_callback(name),
        status_callback=status_callback
    )

    active_conversations[name] = conversation

    # Get number of questions from config
    num_questions = config.get("uat_questions", 10)

    # Start UAT conversation in background
    asyncio.create_task(conversation.start_uat_conversation(num_questions))

    return {"status": "started", "message": "UAT conversation started"}


@app.post("/api/projects/{name}/complete-uat")
async def complete_uat(name: str):
    """Trigger UAT completion and finalization."""
    if name not in active_conversations:
        raise HTTPException(status_code=404, detail="No active UAT conversation for project")

    conversation = active_conversations[name]

    if not conversation.is_active:
        raise HTTPException(status_code=400, detail="UAT conversation is not active")

    if not hasattr(conversation, 'uat_mode') or not conversation.uat_mode:
        raise HTTPException(status_code=400, detail="Not in UAT mode")

    # Signal to complete UAT
    conversation.trigger_uat_completion()

    return {"status": "triggered", "message": "Completing UAT..."}


@app.post("/api/projects/{name}/start-work")
async def start_work(name: str):
    """Start or continue working on the project."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if spec and todo exist
    spec_path = os.path.join(project_path, "SPEC.md")
    todo_path = os.path.join(project_path, "TODO.md")

    if not os.path.exists(spec_path) or not os.path.exists(todo_path):
        raise HTTPException(
            status_code=400,
            detail="Project needs SPEC.md and TODO.md before starting work. Run a kickoff first."
        )

    # Create message callback for work updates
    async def work_message_callback(message: Dict[str, Any]):
        message["project"] = name
        await broadcast_message(message)

    if name not in active_orchestrators:
        active_orchestrators[name] = Orchestrator(
            project_path=project_path,
            config=config,
            activity_callback=create_activity_callback(name),
            message_callback=work_message_callback
        )

    orchestrator = active_orchestrators[name]

    # Start work in background
    asyncio.create_task(orchestrator.start_work())

    return {"status": "started", "message": "Work started"}


@app.post("/api/projects/{name}/pause")
async def pause_work(name: str):
    """Pause work on the project (completes current task first)."""
    if name not in active_orchestrators:
        raise HTTPException(status_code=404, detail="No active work for this project")

    orchestrator = active_orchestrators[name]
    orchestrator.request_pause()

    return {"status": "pausing", "message": "Will pause after current task completes"}


@app.post("/api/projects/{name}/task-decision")
async def task_decision(name: str, req: ChatRequest):
    """Receive user decision for a failed task escalation."""
    if name not in active_orchestrators:
        raise HTTPException(status_code=404, detail="No active work for this project")

    orchestrator = active_orchestrators[name]
    orchestrator.receive_user_decision(req.message)

    return {"status": "received", "message": "Decision received"}


@app.post("/api/projects/{name}/continue")
async def continue_work(name: str):
    """Continue working on the project (alias for start-work)."""
    return await start_work(name)


@app.get("/api/projects/{name}/status")
async def get_project_workflow_status(name: str):
    """Get project workflow status with history."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    status = project_manager.get_workflow_status(name)
    return {
        "name": name,
        "status": status
    }


@app.post("/api/projects/{name}/status")
async def set_project_workflow_status(name: str, req: StatusUpdateRequest):
    """Manually set project workflow status (admin override)."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    new_status_str = req.status.lower()
    reason = req.reason

    try:
        new_status = ProjectStatus.from_string(new_status_str)
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {[s.value for s in ProjectStatus]}"
        )

    result = project_manager.set_workflow_status(
        name=name,
        new_status=new_status,
        agent="user",
        reason=reason
    )

    # Broadcast status change
    await broadcast_message({
        "type": "status_change",
        "project": name,
        "new_status": new_status.value,
        "previous_status": result.get("previous_status"),
        "reason": reason
    })

    return result


@app.get("/api/projects/{name}/qa-notes")
async def get_qa_notes(name: str):
    """Get QA notes for a project."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    notes_path = os.path.join(project_path, "QA", "notes.md")
    if os.path.exists(notes_path):
        with open(notes_path, 'r', encoding='utf-8') as f:
            return {"notes": f.read()}
    return {"notes": ""}


@app.get("/api/projects/{name}/qa-screenshots")
async def list_qa_screenshots(name: str):
    """List screenshots in the QA folder."""
    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    qa_path = os.path.join(project_path, "QA")
    if not os.path.exists(qa_path):
        return {"screenshots": []}

    screenshots = []
    for f in os.listdir(qa_path):
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            screenshots.append({
                "filename": f,
                "path": os.path.join(qa_path, f),
                "url": f"/api/projects/{name}/qa-screenshots/{f}"
            })

    return {"screenshots": screenshots}


@app.get("/api/projects/{name}/qa-screenshots/{filename}")
async def get_qa_screenshot(name: str, filename: str):
    """Get a specific screenshot from the QA folder."""
    from fastapi.responses import FileResponse

    project_path = project_manager.get_project_path(name)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    screenshot_path = os.path.join(project_path, "QA", filename)
    if not os.path.exists(screenshot_path):
        raise HTTPException(status_code=404, detail="Screenshot not found")

    return FileResponse(screenshot_path)


@app.get("/api/playwright/status")
async def get_playwright_status():
    """Get Playwright availability and configuration status."""
    playwright_manager = PlaywrightManager(config)
    return playwright_manager.get_status()


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
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    websocket_connections.append(websocket)

    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            # Could handle incoming messages here if needed
    except WebSocketDisconnect:
        if websocket in websocket_connections:
            websocket_connections.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
