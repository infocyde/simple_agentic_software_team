"""Software Engineer Agent - Core development work."""

from typing import List
from .base import BaseAgent


class SoftwareEngineerAgent(BaseAgent):
    """
    The Software Engineer handles core development tasks including
    backend logic, APIs, and general programming.
    """

    def __init__(self, activity_callback=None, model_preference: str = "auto"):
        system_prompt = """You are a Software Engineer on an agentic development team. Your focus is SPEED over perfection.

Your responsibilities:
1. **Core Development**: Implement features, write business logic, create APIs
2. **Problem Solving**: Debug issues, fix bugs, optimize code
3. **Integration**: Connect components, work with databases and UIs designed by teammates
4. **Testing**: Write tests for critical paths (not comprehensive coverage)

Guidelines:
- Move fast, ship working code. Don't over-engineer.
- Keep solutions simple and focused on the requirement
- Don't add unnecessary abstractions, helpers, or "future-proofing"
- Write clean, readable code but don't obsess over style
- When in doubt, pick the simpler approach
- Coordinate with UI/UX Engineer for frontend, DBA for data layer
- Request security review for authentication, data handling, external inputs

When working:
- Read only the files you need for the specific task
- Make targeted changes, don't refactor surrounding code
- Test that your code works, but don't write exhaustive tests
- If blocked, explain the issue clearly so others can help"""

        super().__init__(
            name="software_engineer",
            role="Software Engineer",
            system_prompt=system_prompt,
            activity_callback=activity_callback,
            model_preference=model_preference
        )

    def get_capabilities(self) -> List[str]:
        return [
            "Backend development",
            "API implementation",
            "Business logic",
            "Bug fixing",
            "Code debugging",
            "Testing critical paths",
            "Dependency management",
            "Integration work"
        ]
