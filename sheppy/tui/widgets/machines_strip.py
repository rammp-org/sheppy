from textual.containers import Horizontal
from textual.widgets import Static

from sheppy.tui.widgets.theme import c


class MachinesStrip(Horizontal):
    """Declared machines from the manifest as chips. Connection status is a
    phase-3 placeholder (glyph is always ○ 'declared, not monitored')."""

    DEFAULT_CSS = """
    MachinesStrip { height: 1; background: $surface; padding: 0 1; }
    MachinesStrip > Static { width: auto; height: 1; margin: 0 1 0 0; }
    MachinesStrip #ms-label { color: $text-muted; margin: 0 2 0 0; }
    /* Compact one-line pills: darker fill stands in for the mockup's
       rounded border (a real border would cost 3 terminal rows). */
    MachinesStrip .chip { background: $chip-bg; padding: 0 1; margin: 0 2 0 0; }
    """

    def __init__(self, machines, **kwargs):
        super().__init__(**kwargs)
        self._machines = list(machines)

    def compose(self):
        yield Static(c("muted", "MACHINES"), id="ms-label")
        if not self._machines:
            yield Static(c("muted", "— none declared —"), id="ms-empty")
        for i, m in enumerate(self._machines):
            chip = f"{c('muted', '○')} {c('fg', m.name)} {c('muted', m.host)}"
            yield Static(chip, id=f"ms-{i}", classes="chip")
        yield Static(c("muted", "· connection status — phase 3"), id="ms-note")
