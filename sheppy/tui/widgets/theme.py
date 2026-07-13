"""Atom One Dark palette and Textual theme — the single source of truth
for Sheppy's colors. Widgets import PALETTE / c() for inline markup and the
app registers SHEPPY_DARK. Do not hardcode hex colors anywhere else."""
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
    """Wrap text in Rich hex markup using a PALETTE color key."""
    return f"[{PALETTE[key]}]{text}[/]"


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
)
