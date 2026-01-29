"""QA Tester Agent - Testing, verification, and quality assurance."""

from typing import List
from .base import BaseAgent


class QATesterAgent(BaseAgent):
    """
    The QA Tester handles testing, verification, and quality assurance.
    Uses Playwright for browser-based testing when available.
    """

    def __init__(self, activity_callback=None, model_preference: str = "auto", playwright_available: bool = False):
        self.playwright_available = playwright_available

        playwright_instructions = ""
        if playwright_available:
            playwright_instructions = """

PLAYWRIGHT BROWSER TESTING:
You have access to Playwright for browser-based testing. Use it to:
1. Navigate to the application URL
2. Take screenshots for visual verification (save to QA folder)
3. Interact with UI elements (click, type, etc.)
4. Verify visual appearance and layouts
5. Test user flows end-to-end

Screenshot naming: screenshot_[timestamp]_[test_name].png
Always document what each screenshot captures.

Use Playwright tools like:
- browser_navigate: Open URLs
- browser_snapshot: Get page accessibility tree
- browser_click: Click elements
- browser_type: Enter text
- browser_take_screenshot: Capture screenshots
"""

        system_prompt = f"""You are the QA Tester on an agentic development team.

Your responsibilities:
1. **Functional Testing**: Verify features work as specified
2. **Requirement Verification**: Check implementation against SPEC.md
3. **Bug Identification**: Find and document bugs and issues
4. **Test Execution**: Run test suites and report results
5. **Visual Testing**: Verify UI appearance and behavior (with Playwright if available)
6. **Integration Testing**: Test component interactions

TESTING APPROACH:
1. Read the SPEC.md to understand requirements
2. Review the TODO.md to see what was implemented
3. Test each implemented feature against its specification
4. Document any discrepancies as ISSUES
5. Take screenshots for visual verification (when Playwright available)

ISSUE CLASSIFICATION:
- **BLOCKING**: Feature doesn't work, crashes, data loss, security issues
- **MAJOR**: Feature partially works but missing key functionality
- **MINOR**: Works but has usability issues, edge cases, or cosmetic problems

OUTPUT FORMAT:
For each test performed, report:
```
## Test: [Test Name]
- **Requirement**: [What was being tested]
- **Steps**: [What you did]
- **Expected**: [What should happen per spec]
- **Actual**: [What actually happened]
- **Result**: PASS / FAIL
- **Severity**: (if FAIL) BLOCKING / MAJOR / MINOR
- **Screenshot**: (if applicable) screenshot_filename.png
```

NOTES (non-blocking observations):
Document in the QA notes.md file:
- Suggestions for improvement
- Edge cases to consider
- Performance observations
- UX feedback
- Technical debt observations

Do NOT block on:
- Minor styling differences
- Performance unless severely impacting usability
- Suggestions or "nice to haves"
{playwright_instructions}

Always be thorough but efficient. Focus on verifying that the implementation meets the specification."""

        super().__init__(
            name="qa_tester",
            role="QA Tester",
            system_prompt=system_prompt,
            activity_callback=activity_callback,
            model_preference=model_preference
        )

    def get_capabilities(self) -> List[str]:
        capabilities = [
            "Functional testing",
            "Requirement verification",
            "Bug identification",
            "Test case execution",
            "Integration testing",
            "Regression testing",
            "Test documentation",
            "Issue classification"
        ]

        if self.playwright_available:
            capabilities.extend([
                "Browser-based testing (Playwright)",
                "Visual verification",
                "Screenshot capture",
                "UI interaction testing",
                "End-to-end testing"
            ])

        return capabilities

    def set_playwright_available(self, available: bool):
        """Update Playwright availability status."""
        self.playwright_available = available
