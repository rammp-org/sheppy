from textual.containers import Horizontal
from textual.widgets import Static

from sheppy.tui.widgets.theme import c

# Single source of truth for the footer key hints (display only; the actual
# bindings live on the app).
KEYMAP = [
    ("↑↓", "move"),
    ("⏎", "select"),
    ("s", "save"),
    ("l", "load"),
    ("p", "params"),
    ("e", "errors"),
    ("1-4", "tabs"),
]


class StatusFooter(Horizontal):
    """Bottom chrome: key hints + a phase-2b daemon-status placeholder."""

    DEFAULT_CSS = """
    StatusFooter { height: 1; background: $panel; padding: 0 1; }
    StatusFooter > Static { width: auto; height: 1; margin: 0 2 0 0; }
    StatusFooter #sf-spring { width: 1fr; margin: 0; }
    """

    def compose(self):
        for i, (key, label) in enumerate(KEYMAP):
            # Inverse-video key reads as a keycap in a single-row footer (a
            # bordered box would need 3 rows). Label stays muted.
            keycap = f"[reverse] {key} [/]"
            yield Static(f"{keycap} {c('muted', label)}", id=f"sf-{i}")
        yield Static("", id="sf-spring")
        yield Static(c("muted", "sheppyd ○ offline — phase 2b"), id="sf-daemon")
