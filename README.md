# Agentic Software Team

**A fully autonomous AI development team that builds software for you.**

Describe what you want. Answer a few questions. Watch a team of specialized AI agents architect, implement, and deliver your project.

No API keys. No complex setup. Just your existing **Claude Code CLI subscription**.

---

## Why This Exists

You have Claude Code. It's powerful. But it's one agent doing everything.

This project gives you a **team** - specialized agents that collaborate, each focused on what they do best. A Project Manager gathers requirements. Engineers write code. A Security Reviewer catches vulnerabilities before they ship.

The result: better architecture, cleaner code, fewer blind spots.

---

## Features

### Specialized Agent Team

| Agent | Role |
|-------|------|
| **Project Manager** | Runs kickoffs, gathers requirements, creates specs and task lists |
| **Software Engineer** | Backend development, APIs, business logic, core implementation |
| **UI/UX Engineer** | Frontend, user interfaces, styling, user experience |
| **Database Admin** | Schema design, queries, migrations, data layer optimization |
| **Security Reviewer** | Security audits, vulnerability detection, code review |

### Intelligent Task Management

- **Concise task breakdown** - AI generates minimal, meaningful tasks (not 200 micro-steps)
- **Parallel execution** - Multiple agents work simultaneously when tasks allow
- **Auto-retry with self-healing** - Failed tasks get retried with error context
- **Section-based organization** - Tasks grouped logically (Setup, Backend, Frontend, etc.)

### Token-Efficient Context

Each agent starts fresh with **minimal context** - just what it needs:
- Recent decisions (last 5)
- Spec summary (500 chars)
- Related tasks in current section only
- No bloat from completed tasks or unrelated sections

This keeps API costs low and agents focused.

### Live Documentation Lookup

Agents can search for and fetch **current documentation** - not just training data:

```bash
# Agents use DuckDuckGo search to find docs
python utils/search_docs.py "prisma client api"
# Returns: https://www.prisma.io/docs/reference/api-reference/prisma-client-reference

# Then fetch and read the docs with WebFetch
```

No stale knowledge. No guessing at APIs. Current docs for whatever stack you choose.

### Built-in Safety

- **Blocked patterns** - Won't touch `.env`, credentials, API keys
- **Dangerous command detection** - No `rm -rf /` accidents
- **Secret scanning** - Catches hardcoded secrets in code
- **Security-first reviews** - Security issues block progress; style issues don't

---

## Quick Start

### Prerequisites

- **Claude Code CLI** installed and authenticated ([get it here](https://claude.ai/code))
- **Python 3.10+**
- **uv** (recommended for venv management) - [install uv](https://docs.astral.sh/uv/getting-started/installation/)

### Install

```bash
git clone https://github.com/yourrepo/simple_agentic_software_team.git
cd simple_agentic_software_team

# Create a virtual environment (recommended)
uv venv --python 3.11
# Activate it:
#   Windows: .venv\Scripts\activate
#   Mac/Linux: source .venv/bin/activate

pip install -r requirements.txt
```

### Verify Claude CLI

```bash
claude --version
```

### Run

```bash
python main.py
```

Open [http://localhost:8000](http://localhost:8000)

---

## Usage

### Start a New Project

1. Click **+ New** in the sidebar
2. Name your project
3. Click **Start Kickoff**
4. Describe what you want to build
5. Answer the PM's questions (10-20 depending on complexity)
6. Click **Write Spec** when ready
7. Click **Start Work** - agents take over

### Add Features Later

1. Select your project
2. Click **Add Feature**
3. Describe the feature
4. Answer clarifying questions
5. Agents update the spec and implement

### Monitor Progress

- **Activity** - Real-time feed of what agents are doing
- **Spec** - Living project specification
- **TODO** - Task list with completion status
- **Team Status** - Which agents are currently working

---

## How It Works

```
You describe project
       |
       v
  [Project Manager]
       |
  Asks 10-20 questions
       |
       v
  Creates SPEC.md + TODO.md
       |
       v
  [Orchestrator]
       |
  Routes tasks to specialists
       |
       +--> [Software Engineer] -- backend code
       |
       +--> [UI/UX Engineer] ----- frontend code
       |
       +--> [Database Admin] ----- schema, queries
       |
       +--> [Security Reviewer] -- audits everything
       |
       v
  Working software in /projects/your-project/
```

Each agent is a **fresh Claude Code CLI invocation** with:
- Specialized system prompt for its role
- Minimal, relevant context
- Full tool access (files, commands, web)
- Auto-selected model (Opus for complex, Sonnet for simple)

---

## Configuration

Edit `config.json`:

```json
{
  "defaults": {
    "testing_strategy": "critical_paths",
    "review_policy": "tiered",
    "autonomy_level": "full"
  },
  "model_routing": {
    "enabled": true,
    "models": {
      "powerful": "claude-opus-4-20250514",
      "fast": "claude-sonnet-4-20250514"
    }
  },
  "execution": {
    "max_concurrent_agents": 3,
    "task_timeout": 300
  }
}
```

### Testing Strategies

| Strategy | Description |
|----------|-------------|
| `minimal` | No tests unless explicitly requested |
| `smoke_tests` | Basic "does it run" tests |
| `critical_paths` | Tests for important functionality (default) |
| `full_tdd` | Test-driven development |

### Review Policies

| Policy | Description |
|--------|-------------|
| `blocking` | All issues block progress |
| `advisory` | All issues are suggestions only |
| `tiered` | Security blocks, style advises (default) |

---

## Project Structure

```
simple_agentic_software_team/
  agents/           # Agent definitions (PM, Engineer, etc.)
  core/             # Orchestration, memory, conversation management
  utils/            # Utilities (doc search, etc.)
  web/              # Dashboard UI
  projects/         # Your projects live here
  config.json       # Global configuration
  main.py           # Entry point
```

Each project you create:

```
projects/my-app/
  SPEC.md           # Project specification
  TODO.md           # Task list with checkboxes
  MEMORY.md         # Decisions and lessons learned
  src/              # Your actual code
  .git/             # Version controlled from the start
```

---

## API

For programmatic access or building your own UI:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects` | GET | List all projects |
| `/api/projects` | POST | Create new project |
| `/api/projects/{name}` | GET | Get project details |
| `/api/projects/{name}/kickoff` | POST | Start project kickoff |
| `/api/projects/{name}/feature` | POST | Start feature request |
| `/api/projects/{name}/work` | POST | Start/continue work |
| `/ws` | WebSocket | Real-time activity stream |

---

## Troubleshooting

### "claude: command not found"

Install Claude Code CLI from [claude.ai/code](https://claude.ai/code) and ensure it's in your PATH.

### Agents timing out

Increase timeout in `config.json`:
```json
"execution": {
  "task_timeout": 600
}
```

### Want more/fewer kickoff questions

Adjust in `config.json`:
```json
"project_kickoff_questions": 15,
"feature_kickoff_questions": 8
```

---

## Cost Efficiency

This system is designed to minimize token usage:

- **Minimal context per task** - Agents get only what they need
- **Smart model routing** - Sonnet for simple tasks, Opus for complex
- **Concise task lists** - 10-30 meaningful tasks, not 200 micro-steps
- **No context accumulation** - Each task starts fresh

You're already paying for Claude Code. This just uses it smarter.

---

## Contributing

PRs welcome. The codebase is straightforward:

- Add new agents in `agents/`
- Modify orchestration in `core/orchestrator.py`
- Tweak prompts in agent `system_prompt` fields
- Adjust context in `core/memory.py`

---

## License

MIT

---

**Built with Claude Code, for Claude Code users.**
