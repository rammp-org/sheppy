from datetime import datetime

from textual.containers import Horizontal
from textual.markup import escape
from textual.widgets import Static

from sheppy.tui.widgets.theme import c


class HeaderBar(Horizontal):
    """Top chrome: brand · profile chip · source · (spacer) · errors · clock.
    Presentational — the app pushes state in via update_state()."""

    DEFAULT_CSS = """
    HeaderBar { height: 1; background: $panel; padding: 0 1; }
    HeaderBar > Static { width: auto; height: 1; }
    HeaderBar #hb-spring { width: 1fr; }
    HeaderBar #hb-errors { margin: 0 2 0 0; }
    HeaderBar .hb-sep { color: $chip-border; margin: 0 1; }
    """

    def compose(self):
        yield Static(c("green", "🐑 sheppy"), id="hb-brand")
        yield Static("│", classes="hb-sep")
        yield Static("", id="profilebar")
        yield Static("│", classes="hb-sep")
        yield Static("", id="hb-source")
        yield Static("", id="hb-spring")
        yield Static("", id="hb-errors")
        yield Static("│", classes="hb-sep")
        yield Static("", id="hb-clock")

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self.query_one("#hb-clock", Static).update(
            c("muted", f"◷ {datetime.now().strftime('%H:%M:%S')}"))

    def update_state(self, profile_name, dirty, path, node_count,
                     error_count, running: "int | None" = None) -> None:
        name = profile_name or "<none>"
        dirty_mark = c("yellow", "*") if dirty else ""
        self.query_one("#profilebar", Static).update(
            f"{c('purple', '◆ profile')} {escape(name)}{dirty_mark}")
        source = c("muted", f"{path or '<no file>'} · {node_count} nodes")
        if running is not None:
            source += f" {c('muted', '·')} {c('green', f'● {running} running')}"
        self.query_one("#hb-source", Static).update(source)
        if error_count:
            errtext = c("red", f"✕ {error_count} error(s)")
        else:
            errtext = c("muted", "✓ no errors")
        self.query_one("#hb-errors", Static).update(errtext)
