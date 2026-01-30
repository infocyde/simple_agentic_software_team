# Night Ronin's Agentic Software Team

**A fully autonomous AI development team that builds software for you.**

![NightRonin](web/static/night-ronin.png)

> **Experimental Software** — This project is under active development and provided as-is, with no warranties or guarantees. Use at your own risk. By design, this tool spawns multiple concurrent Claude Code CLI processes. While this does not violate Anthropic's Terms of Service, setting `max_concurrent_agents` to an excessively high value may trigger rate limits or draw scrutiny from Anthropic. Use reasonable concurrency settings and monitor your usage accordingly. Additionally, execution speed is still being optimized — expect slower-than-ideal runtimes as we continue to improve performance.

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
| **Testing Agent** | Test creation and execution (before security review) |
| **Security Reviewer** | Security audits, vulnerability detection, code review |
| **QA Tester** | Automated QA passes (optionally via Playwright) |

### Intelligent Task Management

- **Concise task breakdown** - AI generates minimal, meaningful tasks (not 200 micro-steps)
- **Parallel execution** - Multiple agents work simultaneously when tasks allow (cross-section optional)
- **Auto-retry with self-healing** - Failed tasks get retried with error context
- **Section-based organization** - Tasks grouped logically (Setup, Backend, Frontend, etc.)
- **Workflow statuses** - Project moves through WIP → Testing → Security Review → QA → UAT → Done
- **Test creation/update** - For `critical_paths` and `full_tdd`, a minimal pytest suite is created and updated as code changes

### Token-Efficient Context

Each agent receives **minimal injected context** - just what it needs:
- Recent decisions (last 5)
- Sibling tasks in the current section only (max 3, uncompleted only)
- No spec dump, no completed tasks, no unrelated sections

With **session continuity** enabled, agents retain codebase knowledge from prior tasks — no re-reading files they already know. This keeps API costs low and agents focused.

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
- **QA review** - Automated QA pass after implementation (can be disabled)

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

Open [http://localhost:8080](http://localhost:8080) (default port, configurable via `server_port` in config.json)

---

## Usage

### Start a New Project

1. Click **+ New** in the sidebar
2. Name your project
3. (Optional) Check **Fast Project** to skip Testing, Security, and QA by default
3. Click **Start Kickoff**
4. Describe what you want to build
5. Answer the PM's questions (10-20 depending on complexity)
6. Click **Write Spec** when ready
7. Click **Start Work** - agents take over
8. When prompted, click **Start UAT** to review and approve

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
- **Workflow Status** - WIP → Testing → Security Review → QA → UAT → Done

---

## Workflow Statuses

- **WIP** - Agents are implementing tasks from TODO.md
- **Security Review** - Security reviewer audits code (blocking issues reopen TODO)
- **Testing** - Testing agent creates/updates tests and runs them (when enabled)
- **QA** - QA tester verifies requirements and critical flows
- **UAT** - User acceptance testing with you in the UI
- **Done** - Approved in UAT

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
       +--> [Testing Agent] ----- builds/updates tests
       |
       +--> [Security Reviewer] -- audits everything
       |
       +--> [QA Tester] ---------- requirements verification
       |
       v
  UAT with you → Done
```

Workflow summary:

```
WIP → Testing → Security Review → QA → UAT → Done
```

### Agent Execution Model

Each agent runs as a **Claude Code CLI process** (`claude --print`):
- Specialized system prompt for its role
- Minimal, relevant context (recent decisions + sibling tasks)
- Full tool access (files, commands, web)
- Auto-selected model (Opus for complex, Sonnet for simple)
- **Prompts piped via stdin** — no Windows command-line length limits (previously capped at ~30K chars)

**Concurrency:** Each agent type has its own CLI session, but only `max_concurrent_agents` run at once (controlled by an asyncio semaphore). Setting this to 2 means two agents work in parallel; the rest queue.

**Session Continuity:** When `session_continuity` is enabled in config, agents reuse their Claude CLI session across tasks via `--resume <session_id>`. This eliminates cold-start overhead — the agent remembers the codebase, previous decisions, and files from earlier tasks. Sessions reset automatically when a new project or feature starts. Disable with `"session_continuity": false` to revert to stateless mode.

**Timeouts:** Timeouts are not retried (a timed-out prompt will almost certainly time out again). Exceptions are retried up to `max_task_retries` times with error context appended so the agent can adapt.

**Task Splitting:** Large tasks are automatically split into subtasks. Complexity is estimated from the clean task description (ignoring retry metadata) to avoid false positives.

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
  "quality_gates": {
    "run_security_review": true,
    "run_qa_review": true,
    "run_tests": true
  },
  "playwright": {
    "enabled": true,
    "auto_detect": true,
    "screenshot_dir": "QA",
    "browser": "chromium",
    "headless": false
  },
  "model_routing": {
    "enabled": true,
    "models": {
      "powerful": "claude-opus-4-20250514",
      "fast": "claude-sonnet-4-20250514"
    }
  },
  "execution": {
    "max_concurrent_agents": 2,
    "task_timeout_seconds": 600,
    "simple_task_timeout_seconds": 600,
    "max_task_retries": 2,
    "allow_cross_section_parallel": true,
    "enable_task_batching": true,
    "task_batch_size": 7,
    "session_continuity": true
  }
}
```

Quality gates can be overridden per project in the UI (saved in `STATUS.json`), along with a per‑project `testing_strategy` when Fast mode is enabled. Example:

```json
{
  "current_status": "initialized",
  "testing_strategy": "smoke",
  "quality_gates": {
    "run_security_review": false,
    "run_qa_review": false,
    "run_tests": false
  }
}
```

### Fast Project Mode

Fast mode is a per‑project preset that:
- Disables **Testing**, **Security Review**, and **QA Review** gates
- Sets testing strategy to **smoke** (so if tests are re‑enabled later, only smoke tests run)

You can enable this when creating a project via the **Fast Project** checkbox in the UI.

### QA + Playwright (Optional)

The QA step can use the Playwright MCP server inside Claude Code for browser-based testing and screenshots.

To enable it:
1. Install the MCP server (npm): `npm i -g @anthropic/mcp-server-playwright`
2. Register it with Claude Code by adding it to your `mcp_servers.json` (location varies):
   - `~/.claude/mcp_servers.json`
   - `~/.config/claude/mcp_servers.json`
   - `%APPDATA%\\claude\\mcp_servers.json`
3. Keep `playwright.enabled` set to `true` in `config.json`.

If you don't want browser-based QA, set `playwright.enabled` to `false`. The QA agent will still run, but without Playwright automation.

### Testing Strategies

| Strategy | Description |
|----------|-------------|
| `minimal` | No tests run |
| `smoke_tests` | Run existing tests only |
| `critical_paths` | Auto-create/update minimal pytest suite + run tests |
| `full_tdd` | Require tests; auto-create/update and fail if none exist |

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
  SUMMARY.md        # Completion summary (after done)
  log.md            # Full Claude CLI call log (prompts + results)
  error_log.md      # Error and timeout details
  QA/               # QA notes and screenshots
  src/              # Your actual code
  .git/             # Version controlled from the start
```

---

## API

For programmatic access or building your own UI:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects` | GET | List all projects |
| `/api/projects` | POST | Create new project (accepts `fast_project: true` to enable Fast mode) |
| `/api/projects/{name}` | GET | Get project details |
| `/api/projects/{name}/kickoff` | POST | Start project kickoff |
| `/api/projects/{name}/feature` | POST | Start feature request |
| `/api/projects/{name}/chat` | POST | Send user message to active conversation |
| `/api/projects/{name}/write-spec` | POST | Create SPEC.md and TODO.md |
| `/api/projects/{name}/start-work` | POST | Start/continue work |
| `/api/projects/{name}/pause` | POST | Pause current work |
| `/api/projects/{name}/continue` | POST | Resume work |
| `/api/projects/{name}/status` | GET/POST | Read or set workflow status |
| `/api/projects/{name}/quality-gates` | GET/PUT | Get or update quality gates |
| `/api/projects/{name}/activity` | GET | Recent activity log |
| `/api/projects/{name}/summary` | GET | Completion summary |
| `/api/projects/{name}/spec` | GET | SPEC.md contents |
| `/api/projects/{name}/todo` | GET | TODO.md contents |
| `/api/projects/{name}/uat` | POST | Start UAT conversation |
| `/api/projects/{name}/complete-uat` | POST | Complete UAT |
| `/api/projects/{name}/qa-notes` | GET | QA notes |
| `/api/projects/{name}/qa-screenshots` | GET | QA screenshots list |
| `/api/projects/{name}/qa-screenshots/{filename}` | GET | QA screenshot file |
| `/api/projects/{name}/task-decision` | POST | Resolve task failure escalation |
| `/api/playwright/status` | GET | Playwright availability |
| `/ws` | WebSocket | Real-time activity stream |

---

## Troubleshooting

### "claude: command not found"

Install Claude Code CLI from [claude.ai/code](https://claude.ai/code) and ensure it's in your PATH.

### Agents timing out

Increase timeouts in `config.json`:
```json
"execution": {
  "task_timeout_seconds": 600,
  "simple_task_timeout_seconds": 600
}
```

### Agents stuck in a split loop

If the orchestrator keeps splitting a task without executing it, check TODO.md for malformed lines (e.g. leftover retry messages parsed as separate tasks). Clean up the TODO and restart work.

### Want more/fewer kickoff questions

Adjust in `config.json`:
```json
"project_kickoff_questions": 15,
"feature_kickoff_questions": 8
```

---

## Cost Efficiency

This system is designed to minimize token usage:

- **Session continuity** - Agents resume their CLI session across tasks, eliminating cold-start re-discovery of the codebase
- **Minimal injected context** - Only recent decisions and sibling tasks; agents read files themselves as needed
- **Smart model routing** - Sonnet for simple tasks, Opus for complex
- **Concise task lists** - 10-30 meaningful tasks, not 200 micro-steps
- **No timeout retries** - Timed-out tasks escalate instead of burning tokens retrying
- **Error-aware retries** - Exception retries include the previous error so the agent adapts instead of repeating the same mistake

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

**Built with Claude Code, for Claude Code users. Also reviewed and updated by OpenAI Codex. Opus rules but Codex is faster and a better architect.**
