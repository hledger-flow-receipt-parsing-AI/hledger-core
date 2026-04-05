"""AISuggestion dataclass — shared across the hledger ecosystem.

Moved here from tui-image-labeller so any package (including hledger-ai)
can produce suggestions without depending on urwid.
"""

from dataclasses import dataclass


@dataclass
class AISuggestion:
    question: str
    probability: float
    model_name: str
