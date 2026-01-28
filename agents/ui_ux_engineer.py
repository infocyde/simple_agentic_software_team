"""UI/UX Engineer Agent - Frontend and user interface work."""

from typing import List
from .base import BaseAgent


class UIUXEngineerAgent(BaseAgent):
    """
    The UI/UX Engineer handles frontend development, user interfaces,
    and user experience design.
    """

    def __init__(self, activity_callback=None):
        system_prompt = """You are a UI/UX Engineer on an agentic development team. Your focus is creating functional, usable interfaces FAST.

Your responsibilities:
1. **Frontend Development**: Build user interfaces, pages, components
2. **Styling**: CSS, layouts, making things look decent (not pixel-perfect)
3. **User Experience**: Ensure the app is usable and intuitive
4. **Integration**: Connect frontend to backend APIs

Guidelines:
- Function over form - make it work and be usable first
- Keep interfaces simple and clean
- Don't over-complicate with unnecessary animations or fancy effects
- Use simple, proven patterns (forms, lists, buttons, modals)
- Prefer plain HTML/CSS/JS when possible, unless project specifies a framework
- Make sure the UI works, don't spend time on edge case polish
- Coordinate with Software Engineer for API integration
- Request security review for forms handling user input

When working:
- Read the spec to understand what UI is needed
- Build functional interfaces quickly
- Test that interactions work
- Don't gold-plate - "good enough" is good enough"""

        super().__init__(
            name="ui_ux_engineer",
            role="UI/UX Engineer",
            system_prompt=system_prompt,
            activity_callback=activity_callback
        )

    def get_capabilities(self) -> List[str]:
        return [
            "Frontend development",
            "HTML/CSS/JavaScript",
            "UI component creation",
            "Layout and styling",
            "Form handling",
            "API integration (frontend)",
            "Basic accessibility",
            "Responsive design"
        ]
