"""Atom One Dark palette and Textual theme — the single source of truth
for Sheppy's colors. Widgets import PALETTE / c() for inline markup and the
app registers SHEPPY_DARK. Do not hardcode hex colors anywhere else."""
from textual.markup import escape
from textual.theme import Theme

PALETTE = {
    "bg": "#282c34",
    "surface": "#21252b",
    "panel": "#1b1e24",
    "fg": "#abb2bf",
    "muted": "#5c6370",
    "green": "#98c379",
    "purple": "#c678dd",
    "blue": "#61afef",
    "red": "#e06c75",
    "yellow": "#e5c07b",
    "orange": "#d19a66",
    "border": "#2c313a",
}


def c(key: str, text: str) -> str:
    """Wrap text in Rich hex markup using a PALETTE color key. The text is
    escaped first so caller-supplied/user data can never be parsed as
    markup (e.g. a node name containing '[/x]' must render literally, not
    raise textual.markup.MarkupError)."""
    return f"[{PALETTE[key]}]{escape(str(text))}[/]"


SHEPPY_DARK = Theme(
    name="sheppy-dark",
    primary=PALETTE["blue"],
    secondary=PALETTE["purple"],
    accent=PALETTE["green"],
    foreground=PALETTE["fg"],
    background=PALETTE["bg"],
    surface=PALETTE["surface"],
    panel=PALETTE["panel"],
    success=PALETTE["green"],
    warning=PALETTE["yellow"],
    error=PALETTE["red"],
    dark=True,
    # Custom CSS variables (referenced as $name in widget DEFAULT_CSS) so the
    # cockpit's structural colors stay single-sourced here, not in each widget.
    variables={
        "sel-bg": "#2f3947",      # highlighted/selected row background
        "chip-bg": "#242832",     # machine/keycap chip fill
        "chip-border": "#3b4048", # chip outline
        "divider": "#14171c",     # thin line between panes
        # Tame Textual's default list cursor (a bright accent block) into the
        # cockpit's subtle selection look, with readable text.
        "block-cursor-background": "#2f3947",
        "block-cursor-foreground": "#e6e9ef",
        "block-cursor-text-style": "bold",
        "block-cursor-blurred-background": "#2b323d",
        "block-cursor-blurred-foreground": "#abb2bf",
        "block-cursor-blurred-text-style": "none",
        # Scrollbars recede into the surface instead of the default blue.
        "scrollbar": "#2c313a",
        "scrollbar-hover": "#3b4048",
        "scrollbar-active": "#3b4048",
        "scrollbar-background": "#21252b",
        "scrollbar-background-hover": "#21252b",
        "scrollbar-background-active": "#21252b",
    },
)
