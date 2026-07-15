from textual.app import App

from sheppy.tui.widgets.theme import SHEPPY_DARK


class ThemedApp(App):
    """Base test harness that installs Sheppy's theme, mirroring how the real
    SheppyApp runs. The cockpit widgets reference the theme's custom CSS
    variables ($sel-bg, $chip-border, $divider, …), so mounting them without
    the theme would raise UnresolvedVariableError — exactly as it would if a
    widget were used outside SheppyApp."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.register_theme(SHEPPY_DARK)
        self.theme = "sheppy-dark"
