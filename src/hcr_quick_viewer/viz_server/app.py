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
from hcr_quick_viewer.viz_server import theme

pn.extension(sizing_mode="stretch_width")

# -- tabs ------------------------------------------------------------------

single_mouse_tab = SingleMouseTab()
compare_tab = CompareTab()

# -- sidebar (swapped when tabs change) ------------------------------------

sidebar_col = pn.Column(sizing_mode="stretch_width")


def _populate_sidebar(tab_obj) -> None:
    """Replace sidebar contents with the active tab's widgets."""
    sidebar_col.objects = tab_obj.sidebar_widgets()


# -- main content (swapped when tabs change) -------------------------------

single_main = single_mouse_tab.main_area()
compare_main = compare_tab.main_area()

tabs = pn.Tabs(
    ("Single Mouse", single_main),
    ("Compare Mice", compare_main),
    sizing_mode="stretch_both",
    dynamic=True,
)


def _on_tab_change(event) -> None:
    active = event.new
    tab_obj = single_mouse_tab if active == 0 else compare_tab
    _populate_sidebar(tab_obj)


tabs.param.watch(_on_tab_change, "active")

# -- refresh button --------------------------------------------------------

refresh_btn = pn.widgets.Button(name="↺ Refresh", button_type="warning", width=100)


def _on_refresh(event) -> None:
    catalog.refresh()
    image_cache.clear()
    single_mouse_tab.reload()
    compare_tab.reload()


refresh_btn.on_click(_on_refresh)

# -- template --------------------------------------------------------------

template = pn.template.FastListTemplate(
    title="HCR QC Viewer",
    sidebar=[sidebar_col],
    main=[tabs],
    header_background="#2b579a",
    accent_base_color="#2b579a",
    sidebar_width=theme.SIDEBAR_WIDTH,
    raw_css=theme.raw_css(),
)

# Refresh button in the sidebar header area
sidebar_col.insert(0, refresh_btn)
sidebar_col.insert(1, pn.layout.Divider())

# -- initial load ----------------------------------------------------------

try:
    single_mouse_tab.reload()
    compare_tab.reload()
except Exception as exc:
    template.main.append(
        pn.pane.Alert(
            f"Failed to load catalog from S3: {exc}. "
            "Check AWS credentials and try the ↺ Refresh button.",
            alert_type="warning",
        )
    )

_populate_sidebar(single_mouse_tab)

# -- keyboard navigation --------------------------------------------------
# Inject a JS keydown listener that finds the hidden IntInput (tagged
# "hcr-keynav") and increments/decrements its value on arrow keys.
# The Python-side param.watch callback picks up the change.

_keynav_js = pn.pane.HTML("""
<script>
document.addEventListener("keydown", function(e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    // Don't hijack arrows when user is typing in an input
    var tag = document.activeElement && document.activeElement.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    var docs = window.Bokeh && Bokeh.documents;
    if (!docs || !docs.length) return;
    var models = docs[0].roots();
    for (var i = 0; i < models.length; i++) {
        // Walk the model tree to find our tagged IntInput
        var found = _findKeynav(models[i]);
        if (found) {
            if (e.key === "ArrowRight") found.value += 1;
            else found.value -= 1;
            e.preventDefault();
            return;
        }
    }
});
function _findKeynav(model) {
    if (model.tags && model.tags.indexOf("hcr-keynav") !== -1) return model;
    if (model.children) {
        for (var j = 0; j < model.children.length; j++) {
            var c = Array.isArray(model.children[j])
                ? model.children[j] : [model.children[j]];
            for (var k = 0; k < c.length; k++) {
                var r = _findKeynav(c[k]);
                if (r) return r;
            }
        }
    }
    return null;
}
</script>
""", width=0, height=0, sizing_mode="fixed", visible=False)
template.main.append(_keynav_js)

template.servable()
