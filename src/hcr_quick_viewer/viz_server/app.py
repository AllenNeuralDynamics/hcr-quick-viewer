"""HCR QC Viewer — Panel application entrypoint.

Launch with:
    panel serve src/hcr_quick_viewer/viz_server/app.py \
        --address 0.0.0.0 --port 5006 \
        --allow-websocket-origin "*" \
        --num-threads 4
"""

from __future__ import annotations

import panel as pn

from hcr_quick_viewer.viz_server import catalog, image_cache
from hcr_quick_viewer.viz_server.tabs.single_mouse import SingleMouseTab
from hcr_quick_viewer.viz_server.tabs.compare import CompareTab

pn.extension(sizing_mode="stretch_width")

# -- tabs ------------------------------------------------------------------

single_mouse_tab = SingleMouseTab()
compare_tab = CompareTab()

# -- global controls -------------------------------------------------------

refresh_btn = pn.widgets.Button(name="↺ Refresh", button_type="warning", width=100)


def _on_refresh(event) -> None:
    catalog.refresh()
    image_cache.clear()
    single_mouse_tab.reload()
    compare_tab.reload()


refresh_btn.on_click(_on_refresh)

# -- header ----------------------------------------------------------------

header = pn.Row(
    pn.pane.Markdown("# HCR QC Viewer", sizing_mode="stretch_width"),
    refresh_btn,
    sizing_mode="stretch_width",
    styles={"padding": "5px 15px"},
)

# -- main layout -----------------------------------------------------------

tabs = pn.Tabs(
    ("Single Mouse", single_mouse_tab),
    ("Compare Mice", compare_tab),
    sizing_mode="stretch_both",
)

layout = pn.Column(header, tabs, sizing_mode="stretch_both")

# -- initial load ----------------------------------------------------------

try:
    single_mouse_tab.reload()
    compare_tab.reload()
except Exception as exc:
    layout.append(
        pn.pane.Alert(
            f"Failed to load catalog from S3: {exc}. "
            "Check AWS credentials and try the ↺ Refresh button.",
            alert_type="warning",
        )
    )

layout.servable(title="HCR QC Viewer")
