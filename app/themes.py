"""Invitation card themes and layouts.

A **theme** is the palette and typography; a **layout** is the arrangement of
the card. They are independent, so any theme works with any layout.

Everything the picker needs to draw a preview lives here, so adding a theme is
one entry in this file plus one block of custom properties in `invite.css`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    description: str
    mood: str  # "formal" or "cheerful" -- groups the picker
    font_query: Optional[str]  # Google Fonts css2 family fragment
    ornament: str
    # Swatch colours, used to render the picker preview without loading the
    # full stylesheet for every theme.
    paper: str
    ink: str
    accent: str
    edge: str
    preview_font: str


THEMES: Tuple[Theme, ...] = (
    Theme(
        name="classic",
        label="Classic Ivory",
        description="Formal, ivory and gold. The traditional choice.",
        mood="formal",
        font_query="family=Cormorant+Garamond:wght@400;600",
        ornament='"\\2726"',
        paper="#fffdf8", ink="#262119", accent="#9a7b3f", edge="#e4dbc9",
        preview_font="'Cormorant Garamond', Georgia, serif",
    ),
    Theme(
        name="midnight",
        label="Midnight",
        description="Black tie. Deep charcoal with antique gold.",
        mood="formal",
        font_query="family=Playfair+Display:wght@400;600",
        ornament='"\\2727"',
        paper="#17171d", ink="#ece9e3", accent="#c9a227", edge="#343241",
        preview_font="'Playfair Display', Georgia, serif",
    ),
    Theme(
        name="bloom",
        label="Bloom",
        description="Soft rose and blush. Weddings, showers, spring.",
        mood="formal",
        font_query="family=Gilda+Display",
        ornament='"\\273F"',
        paper="#fffafb", ink="#3b2430", accent="#c2547d", edge="#f4d9e2",
        preview_font="'Gilda Display', Georgia, serif",
    ),
    Theme(
        name="nordic",
        label="Nordic",
        description="Clean and quiet. Plenty of white space, no ornament.",
        mood="formal",
        font_query="family=Inter:wght@400;600",
        ornament='""',
        paper="#ffffff", ink="#1c1f23", accent="#3d6b9e", edge="#e2e5e9",
        preview_font="'Inter', -apple-system, sans-serif",
    ),
    Theme(
        name="garden",
        label="Garden Party",
        description="Fresh greens. Daytime, outdoors, summer.",
        mood="cheerful",
        font_query="family=Lora:wght@400;600",
        ornament='"\\2766"',
        paper="#fbfdf7", ink="#22301f", accent="#4a7c3f", edge="#d9e5cf",
        preview_font="'Lora', Georgia, serif",
    ),
    Theme(
        name="sunset",
        label="Sunset",
        description="Warm coral and peach. Relaxed and friendly.",
        mood="cheerful",
        font_query="family=Fraunces:opsz,wght@9..144,400;9..144,600",
        ornament='"\\273B"',
        paper="#fffaf4", ink="#40251a", accent="#e2683c", edge="#ffd9c0",
        preview_font="'Fraunces', Georgia, serif",
    ),
    Theme(
        name="confetti",
        label="Confetti",
        description="Bright and playful. Birthdays and children's parties.",
        mood="cheerful",
        font_query="family=Baloo+2:wght@500;700",
        ornament='"\\273D"',
        paper="#fffdf9", ink="#2c2440", accent="#e94f8a", edge="#ffdfe9",
        preview_font="'Baloo 2', -apple-system, sans-serif",
    ),
    Theme(
        name="neon",
        label="After Dark",
        description="Bold on black. Late nights and loud music.",
        mood="cheerful",
        font_query="family=Space+Grotesk:wght@500;700",
        ornament='"\\25C6"',
        paper="#17131f", ink="#f2ecff", accent="#8b5cf6", edge="#352a4a",
        preview_font="'Space Grotesk', -apple-system, sans-serif",
    ),
)


@dataclass(frozen=True)
class Layout:
    name: str
    label: str
    description: str


LAYOUTS: Tuple[Layout, ...] = (
    Layout("classic", "Centred", "Everything centred beneath an ornament."),
    Layout("banner", "Banner", "A colour band across the top carries the title."),
    Layout("split", "Split", "Details on one side, the RSVP on the other."),
    Layout("minimal", "Minimal", "Left aligned and compact, no ornament."),
)


THEMES_BY_NAME: Dict[str, Theme] = {t.name: t for t in THEMES}
LAYOUTS_BY_NAME: Dict[str, Layout] = {layout.name: layout for layout in LAYOUTS}

THEME_NAMES: Tuple[str, ...] = tuple(THEMES_BY_NAME)
LAYOUT_NAMES: Tuple[str, ...] = tuple(LAYOUTS_BY_NAME)

DEFAULT_THEME = "classic"
DEFAULT_LAYOUT = "classic"


def get_theme(name: Optional[str]) -> Theme:
    """Resolve a theme, falling back to the default rather than failing.

    A card must always render: an unknown name (a renamed theme, a hand-edited
    database row) should degrade to the default, not break someone's invitation.
    """
    return THEMES_BY_NAME.get(name or "", THEMES_BY_NAME[DEFAULT_THEME])


def get_layout(name: Optional[str]) -> Layout:
    return LAYOUTS_BY_NAME.get(name or "", LAYOUTS_BY_NAME[DEFAULT_LAYOUT])


def themes_by_mood() -> List[Tuple[str, List[Theme]]]:
    """Themes grouped for the picker, formal first."""
    return [
        ("Formal", [t for t in THEMES if t.mood == "formal"]),
        ("Cheerful", [t for t in THEMES if t.mood == "cheerful"]),
    ]


def font_query_for(*theme_names: str) -> Optional[str]:
    """One Google Fonts URL covering the given themes.

    The picker needs every theme's face at once so each swatch previews in its
    real typeface; a card needs only its own.
    """
    queries = []
    for name in theme_names:
        query = get_theme(name).font_query
        if query and query not in queries:
            queries.append(query)
    if not queries:
        return None
    return "https://fonts.googleapis.com/css2?" + "&".join(queries) + "&display=swap"


def all_fonts_url() -> Optional[str]:
    return font_query_for(*THEME_NAMES)
