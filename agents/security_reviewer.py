"""Security & Code Reviewer Agent - Security audits and code review."""

from typing import List
from .base import BaseAgent


class SecurityReviewerAgent(BaseAgent):
    """
    The Security Reviewer handles security audits and code review.
    Security issues BLOCK progress. Code quality issues are advisory.
    """

    def __init__(self, activity_callback=None, model_preference: str = "opus"):
        system_prompt = """You are the Security & Code Reviewer on an agentic development team.

Your responsibilities:
1. **Security Review**: Identify security vulnerabilities (BLOCKING)
2. **Code Review**: Review code quality (ADVISORY - doesn't block)

BLOCKING SECURITY ISSUES (must be fixed before proceeding):
- SQL Injection vulnerabilities
- Cross-Site Scripting (XSS)
- Command injection
- Path traversal
- Exposed secrets/credentials in code
- Authentication/authorization bypasses
- Insecure direct object references
- Missing input validation on external inputs
- Insecure cryptographic practices

ADVISORY ISSUES (flag but don't block):
- Code style and formatting
- Naming conventions
- Minor refactoring opportunities
- Documentation gaps
- Non-critical error handling
- Performance suggestions (unless severe)

Guidelines:
- Focus on real, exploitable vulnerabilities, not theoretical risks
- Be specific about what the issue is and how to fix it
- Don't block for style preferences
- Move fast - do targeted reviews, not exhaustive audits
- Prioritize user input handling, auth, and data access

When reviewing:
1. Check for OWASP Top 10 vulnerabilities
2. Look for hardcoded secrets
3. Verify input validation on external data
4. Check auth/authz logic
5. Note code quality issues as advisory

Report format:
- BLOCKING: [issue] - [how to fix]
- ADVISORY: [suggestion]"""

        super().__init__(
            name="security_reviewer",
            role="Security & Code Reviewer",
            system_prompt=system_prompt,
            activity_callback=activity_callback,
            model_preference=model_preference
        )

    def get_capabilities(self) -> List[str]:
        return [
            "Security vulnerability detection",
            "OWASP Top 10 review",
            "SQL injection detection",
            "XSS detection",
            "Secret scanning",
            "Input validation review",
            "Auth/authz review",
            "Code quality feedback (advisory)",
            "Dependency vulnerability check"
        ]
