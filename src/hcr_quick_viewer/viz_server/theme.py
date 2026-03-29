"""Centralized theme configuration for the HCR QC Viewer.

Inspired by Material UI's typography theme_config pattern
(see https://panel-material-ui.holoviz.org/how_to/typography.html).

Edit the values below to adjust fonts and sizes across the entire app.
All font sizes use *rem* so they scale with the user's browser settings.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------

FONT_FAMILY = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)

# Base font size applied to <html>.  1rem = this many px.
HTML_FONT_SIZE_PX = 18

# Component-level sizes (rem).  Increase these to make text bigger.
FONT_SIZE = {
    "base":       "1rem",       # ~16px — body text, widgets
    "sm":         "0.875rem",   # ~14px — secondary labels, links
    "xs":         "0.8rem",     # ~13px — captions, badges
    "card_label": "0.95rem",    # ~15px — plot-card titles
    "header":     "1rem",       # ~16px — compare-tab card headers
    "tab":        "1.1rem",     # ~18px — tab strip labels
}
    
# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

SIDEBAR_WIDTH = 330   # px — template sidebar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def raw_css() -> list[str]:
    """Return a list of CSS strings to inject into the Panel template."""
    return [
        f"""
        html {{
            font-size: {HTML_FONT_SIZE_PX}px;
        }}
        body, .bk, .bk-root, .mdc-typography,
        .bk-btn, .bk-input, select, .pn-loading {{
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE['base']};
        }}
        .bk-tab {{
            font-size: {FONT_SIZE['tab']} !important;
            padding: 8px 18px !important;
        }}
        """
    ]
