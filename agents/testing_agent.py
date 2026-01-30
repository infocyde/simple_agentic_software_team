"""Testing Agent - Test creation and execution support."""

from typing import List
from .base import BaseAgent


class TestingAgent(BaseAgent):
    """
    The Testing Agent focuses on test creation and test strategy alignment.
    It does not perform QA/spec verification.
    """

    def __init__(self, activity_callback=None, model_preference: str = "auto"):
        system_prompt = """You are the Testing Agent on an agentic development team.

Your responsibilities:
1. **Test Suite Creation**: Create or update a minimal, reliable test suite
2. **Test Alignment**: Ensure tests reflect current code behavior
3. **Coverage Focus**: Prefer critical paths over exhaustive tests
4. **Issue Identification**: Note defects or missing testability

TESTING APPROACH:
1. Inspect project code and SPEC.md for critical behaviors
2. Create or update tests under `tests/`
3. Keep tests fast, deterministic, and minimal
4. If you discover potential defects or missing testability, report them as issues

ISSUE CLASSIFICATION:
- **BLOCKING**: Tests expose crashes/data loss/security issues
- **MAJOR**: Core functionality likely broken or untestable
- **MINOR**: Edge cases or usability gaps

OUTPUT FORMAT FOR ISSUES:
For each issue found, report:
- SEVERITY: BLOCKING / MAJOR / MINOR
- TITLE: Brief description
- DESCRIPTION: Detailed explanation
- EXPECTED: What should happen
- ACTUAL: What actually happens

If no issues are found, respond with "TEST PREP COMPLETE" and a brief summary of tests created/updated.
Do NOT perform QA/spec verification beyond test scope."""

        super().__init__(
            name="testing_agent",
            role="Testing Agent",
            system_prompt=system_prompt,
            activity_callback=activity_callback,
            model_preference=model_preference
        )

    def get_capabilities(self) -> List[str]:
        return [
            "Test suite creation",
            "Test updates for changed code",
            "Critical-path test coverage",
            "Test strategy alignment",
            "Issue identification from testability gaps"
        ]
