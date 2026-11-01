from textual.containers import Horizontal
from textual.widgets import Static

from sheppy.tui.widgets.detail_tabs import ParamRow
from sheppy.tui.widgets.theme import c

# Single source of truth for the footer key hints (display only; the actual
# bindings live on the app).
KEYMAP = [
    ("s", "save"),
    ("l", "load"),
    ("p", "params"),
    ("e", "errors"),
    ("1-4", "tabs"),
    ("␣", "apply node"),
    ("x", "stop"),
    ("r", "restart"),
    ("shift+L", "apply all"),
    ("shift+X", "stop all"),
    ("!", "copy running"),
    ("q", "quit"),
]
# Shown instead while a param field has focus (#199).
PARAM_KEYMAP = [("enter", "apply"), ("esc", "revert"), ("tab", "next param")]


class StatusFooter(Horizontal):
    """Bottom chrome: key hints + a phase-2b daemon-status placeholder."""

    DEFAULT_CSS = """
    StatusFooter { height: 1; background: $panel; padding: 0 1; }
    StatusFooter > Static { width: auto; height: 1; margin: 0 1 0 0; }
    StatusFooter .-param, StatusFooter.-param .-keys { display: none; }
    StatusFooter.-param .-param { display: block; }
    StatusFooter #sf-spring { width: 1fr; margin: 0; }
    /* Docked, so it is placed first and the hints are what gets clipped
       when the row is too narrow for everything (#40). */
    StatusFooter #sf-daemon { dock: right; margin: 0; padding-left: 2; }
    """

    def compose(self):
        for keys, cls in ((KEYMAP, "-keys"), (PARAM_KEYMAP, "-param")):
            for key, label in keys:
                # Inverse-video key reads as a keycap in a single-row footer
                # (a bordered box would need 3 rows). Label stays muted.
                keycap = f"[reverse] {key} [/]"
                yield Static(f"{keycap} {c('muted', label)}", classes=cls)
        yield Static("", id="sf-spring")
        yield Static(c("muted", "sheppyd ○ offline"), id="sf-daemon")

    def on_mount(self) -> None:
        self.watch(self.screen, "focused", lambda focused: self.set_class(
            isinstance(focused and focused.parent, ParamRow), "-param"))

    def set_daemon(self, connected: bool, running: int, total: int) -> None:
        if connected:
            text = (f"{c('green', 'sheppyd ●')} "
                    f"{c('fg', f'{running}/{total} running')}")
        else:
            text = c("muted", "sheppyd ○ offline")
        self.query_one("#sf-daemon", Static).update(text)
