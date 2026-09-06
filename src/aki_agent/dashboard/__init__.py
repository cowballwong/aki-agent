"""The dashboard — making the assistant's internal state visible.

WHY A DASHBOARD AT ALL
----------------------
It was nearly cut from this package as a nice-to-have. That would have been a
mistake, and the reason is worth writing down.

For a visual audience, the dashboard is the difference between "I have a
chatbot" and "I have a system". It is also the only thing that makes the
agent's invisible state — what it remembers, what it is holding, what it
thinks is true — permanently inspectable rather than something demonstrated
once in a lesson and then taken on trust.

WHAT MAKES THIS ONE DIFFERENT
-----------------------------
It knows nothing about any profession. Every column, label and grouping comes
from the user's configuration. The same code draws an architect's projects and
a music teacher's students, and there is a test that fails if a single
profession-specific word enters this package's executable code.
"""

from .app import create_app, run  # noqa: F401

__all__ = ["create_app", "run"]
