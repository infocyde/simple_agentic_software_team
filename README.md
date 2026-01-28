# Agentic Software Team

A team of AI agents that collaborate to build software. Uses your **Claude Code CLI subscription** (not the API).

## Team

- **Project Manager** - Coordinates the team, runs kickoffs, manages specs and todos
- **Software Engineer** - Core backend development, APIs, business logic
- **UI/UX Engineer** - Frontend, user interfaces, styling
- **Database Admin** - Schema design, queries, data layer
- **Security Reviewer** - Security audits (blocking), code review (advisory)

## Prerequisites

- **Claude Code CLI** installed and authenticated (`claude` command available)
- Python 3.10+

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Verify Claude CLI

Make sure the `claude` command is available:

```bash
claude --version
```

### 3. Run the Server

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Open the Dashboard

Navigate to [http://localhost:8000](http://localhost:8000)

## Usage

### Creating a New Project

1. Click **+ New** in the projects panel
2. Enter a project name
3. Click **Start Kickoff** and describe what you want to build
4. Answer the PM's questions (15-20 for new projects)
5. The team will create a spec and start working

### Adding Features

1. Select an existing project
2. Click **Add Feature**
3. Describe the feature (~10 questions)
4. Team updates the spec and implements

### Monitoring Progress

- **Activity tab**: Real-time feed of agent actions
- **Spec tab**: Current project specification
- **TODO tab**: Task list with completion status
- **Team Status**: See which agents are working

## How It Works

Each agent is a separate invocation of the Claude Code CLI with a specialized system prompt. When an agent needs to work:

1. The orchestrator builds a prompt with the agent's role and task
2. Invokes `claude --print --dangerously-skip-permissions` with that prompt
3. Claude CLI handles all tool execution (file operations, commands, etc.)
4. Results are captured and logged to the activity feed

This means:
- **No API key needed** - uses your existing Claude Code subscription
- **Full tool access** - agents can read/write files, run commands, etc.
- **Same capabilities as Claude Code** - whatever you can do with `claude`, agents can do

## Configuration

Edit `config.json` to customize:

```json
{
  "defaults": {
    "testing_strategy": "critical_paths",
    "review_policy": "tiered",
    "autonomy_level": "full"
  },
  "guardrails": {
    "require_approval_for": [],
    "blocked_operations": [],
    "max_retries_before_escalation": 3
  },
  "cli": {
    "timeout_seconds": 300,
    "dangerously_skip_permissions": true
  }
}
```

### Testing Strategies

- `minimal` - No automated tests unless requested
- `smoke_tests` - Basic functionality tests
- `critical_paths` - Test important functionality (default)
- `full_tdd` - Test-driven development

### Review Policies

- `blocking` - All issues block progress
- `advisory` - All issues are suggestions
- `tiered` - Security blocks, quality advises (default)

## Project Structure

```
/simple_agentic_software_team/
  /agents/              # Agent definitions
  /core/                # Orchestration, memory, git
  /web/                 # Web interface
  /projects/            # Your projects live here
  config.json           # Global configuration
  main.py               # Entry point
```

Each project gets:

```
/projects/my-project/
  SPEC.md               # Project specification
  TODO.md               # Task list with checkboxes
  MEMORY.md             # Decisions and lessons learned
  SUMMARY.md            # Generated on completion
  /src/                 # Project source code
  .git/                 # Local git repository
```

## Git Workflow

- Agents use git locally for version control
- You handle the final review and push to GitHub
- Changes are committed as work progresses

## Guardrails

The system includes safety guardrails:

- Blocked file patterns (`.env`, credentials, keys)
- Blocked commands (dangerous rm, fork bombs)
- Secret detection in code
- Security issues block progress

Configure in `config.json` under `guardrails`.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects` | GET | List all projects |
| `/api/projects` | POST | Create new project |
| `/api/projects/{name}` | GET | Get project details |
| `/api/projects/{name}/kickoff` | POST | Start project kickoff |
| `/api/projects/{name}/feature` | POST | Start feature request |
| `/api/projects/{name}/continue` | POST | Continue working |
| `/api/projects/{name}/human-input` | POST | Provide human input |
| `/ws` | WebSocket | Real-time activity updates |

## Troubleshooting

### "claude: command not found"

Make sure Claude Code CLI is installed and in your PATH:
- Install from: https://claude.ai/code
- Verify with: `claude --version`

### Agents not responding

Check that your Claude Code subscription is active and you're authenticated:
```bash
claude --print "Hello, are you there?"
```

## License

MIT
