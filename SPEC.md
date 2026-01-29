# Agentic Software Team - System Specification

## Purpose
End-to-end software development system with a bias toward speed over perfection. Builds new software and adds features rapidly.

## Team Composition

### 1. Project Manager (PM)
- Central coordinator for the team
- Runs kickoff questions (15-20 for new projects, 10 for features)
- Creates and manages spec documents and todo lists
- Dispatches tasks to specialists
- Escalates to human when team gets stuck

### 2. Software Engineer
- Core development work
- Implements features and fixes bugs
- Works with modular, scoped context

### 3. UI/UX Engineer
- Frontend development
- User interface design and implementation
- Ensures usable, functional interfaces

### 4. Database Admin (DBA)
- Database schema design
- Query optimization
- Data layer implementation

### 5. Security & Code Reviewer
- Security review (blocking authority)
- Code quality review (advisory)
- Identifies vulnerabilities and issues

### 6. QA Tester
- Automated QA pass after implementation
- Verifies requirements and critical flows
- Can use Playwright MCP server (optional)

## Coordination Model
**Hybrid approach:**
- PM acts as central coordinator
- Agents can collaborate directly when needed
- Parallel work when tasks are independent
- Sequential handoffs when dependencies exist

## LLM Configuration
- Configurable per agent
- Default: Claude Opus for all agents
- Model can be swapped via configuration

## Autonomy & Guardrails
- Fully autonomous by default
- Configurable guardrails per project
- Security issues block progress
- Code quality issues are advisory (don't block)

## Context Management
- **Persistent memory:** Stored in files within project directory
- **Modular context:** Only load relevant code sections, not entire codebase
- **Token efficiency:** Keep context small and focused

## Project Flows

### New Project Kickoff
1. PM asks 15-20 questions to understand requirements
2. PM generates spec document (SPEC.md)
3. PM creates todo list with checkboxes (TODO.md)
4. Work begins with agents tackling tasks
5. Security review runs after tasks complete
6. QA review runs after security passes
7. UAT starts with user approval in the UI

### New Feature Request
1. PM asks ~10 questions to understand the feature
2. PM updates spec and creates feature-specific todos
3. Treated as mini-project within existing codebase

### Workflow Statuses
- **WIP** → **Security Review** → **QA** → **UAT** → **Done**

## Testing Strategy
- **Default:** Test critical paths
- **Configurable:** Can be set per project
- Options: minimal, smoke tests, critical paths, full TDD

## QA Automation (Optional)
- QA step can use Playwright MCP server via Claude Code
- Configured in `config.json` under `playwright`
- Can be disabled by setting `playwright.enabled` to `false`

## Review Policy
- **Tiered (default):**
  - Security issues: Blocking
  - Code quality issues: Advisory
- **Configurable:** Per project or per issue type

## File & Git Integration
- Direct file access within project folder
- Agents use Git for version control locally
- Human handles final review and GitHub push

## Failure Handling
- Self-healing: Agents collaborate to resolve issues
- Escalation: After multiple failed attempts, ask human to intervene

## Project Structure
```
/master-directory/
  /agents/              # Agent definitions (shared)
  /core/                # Orchestration system
  /web/                 # Web interface
  /projects/            # All projects live here
    /project-name/
      .git/
      SPEC.md           # Project specification
      TODO.md           # Checkbox todo list
      MEMORY.md         # Decisions, context, lessons
      /src/             # Project source code
      ...
```

## Web Interface
- Simple, functional design
- Real-time activity feed showing agent actions
- Project status and todo progress
- No build step required (plain HTML/JS/CSS)

## Completion Requirements
When a project/feature is "done":
1. All todo items checked off
2. Security review passed (or issues resolved)
3. QA review passed (or issues resolved)
4. UAT approved by the user
5. Project runs locally (verified)
6. Ready to push to Git
7. Summary report generated:
   - What was built
   - Decisions made and why
   - Possible issues flagged
   - Lessons learned
8. Deployment instructions provided

## Configuration
Global config in `config.json`:
- Default LLM model
- Default testing strategy
- Default review policy
- Guardrail settings
- API keys (via environment variables)
