"""Tab 2 – Compare Mice view.

Shows one plot type across multiple selected mice side-by-side (Row) or
vertically stacked (Stack), with a hide-missing toggle and metadata table.
"""

from __future__ import annotations

from io import BytesIO

import panel as pn
import param

from hcr_quick_viewer.viz_server import catalog, image_cache


class CompareTab(pn.viewable.Viewer):
    """Multi-mouse comparison tab."""

    selected_plot_type = param.String(default="")
    layout_mode = param.Selector(
        default="↔ Row", objects=["↔ Row", "↕ Stack"],
    )
    hide_missing = param.Boolean(default=False)

    def __init__(self, **params):
        super().__init__(**params)

        self._plot_type_select = pn.widgets.Select(
            name="Plot type", options=[], width=200,
        )
        self._mice_selector = pn.widgets.CheckBoxGroup(
            name="Mice", options=[], inline=False,
        )
        self._layout_toggle = pn.widgets.RadioButtonGroup(
            name="Layout", options=["↔ Row", "↕ Stack"], value="↔ Row", width=200,
        )
        self._hide_missing_cb = pn.widgets.Checkbox(
            name="Hide missing plots", value=False,
        )
        self._image_area = pn.Column(sizing_mode="stretch_width")
        self._meta_table = pn.pane.Markdown("", sizing_mode="stretch_width")

        self._plot_type_select.param.watch(self._on_plot_type_change, "value")
        self._mice_selector.param.watch(self._on_selection_change, "value")
        self._layout_toggle.param.watch(self._on_layout_change, "value")
        self._hide_missing_cb.param.watch(self._on_hide_change, "value")

    # -- public API --------------------------------------------------------

    def reload(self) -> None:
        """Refresh catalog data and rebuild widgets."""
        cat = catalog.load_catalog()
        plot_types = catalog.known_plot_types(cat)
        mice = catalog.mice_in_catalog(cat)

        self._plot_type_select.options = plot_types
        self._mice_selector.options = mice
        self._mice_selector.value = mice  # select all by default

        if plot_types and self._plot_type_select.value not in plot_types:
            self._plot_type_select.value = plot_types[0]
        else:
            self._rebuild_comparison()

    # -- callbacks ---------------------------------------------------------

    def _on_plot_type_change(self, event) -> None:
        self.selected_plot_type = event.new
        self._rebuild_comparison()

    def _on_selection_change(self, event) -> None:
        self._rebuild_comparison()

    def _on_layout_change(self, event) -> None:
        self.layout_mode = event.new
        self._rebuild_comparison()

    def _on_hide_change(self, event) -> None:
        self.hide_missing = event.new
        self._rebuild_comparison()

    def _rebuild_comparison(self) -> None:
        """Rebuild the image area and metadata table."""
        plot_type = self._plot_type_select.value
        selected_mice = self._mice_selector.value or []

        if not plot_type or not selected_mice:
            self._image_area.objects = []
            self._meta_table.object = ""
            return

        cat = catalog.load_catalog()
        mice_with_plot = set(catalog.mice_for_plot_type(cat, plot_type))

        cards = []
        meta_rows = []
        for mid in selected_mice:
            has_plot = mid in mice_with_plot

            if not has_plot and self.hide_missing:
                continue

            if has_plot:
                data = image_cache.get_plot_bytes(mid, plot_type, fmt="png")
                if data:
                    img = pn.pane.PNG(
                        object=BytesIO(data),
                        sizing_mode="scale_width" if self.layout_mode == "↕ Stack" else "fixed",
                        width=350 if self.layout_mode == "↔ Row" else None,
                        max_width=1200,
                    )
                else:
                    img = self._missing_placeholder(mid)
                    has_plot = False
            else:
                img = self._missing_placeholder(mid)

            header = pn.pane.HTML(
                f'<b>{mid}</b>',
                styles={"font-size": "0.9em"},
            )
            card = pn.Card(
                header, img,
                width=370 if self.layout_mode == "↔ Row" else None,
                sizing_mode="stretch_width" if self.layout_mode == "↕ Stack" else "fixed",
                hide_header=True,
            )
            cards.append(card)

            # Build metadata row
            if has_plot:
                meta = catalog.load_plot_metadata(mid, plot_type)
                created = meta.get("created_at", "—") if meta else "—"
                version = meta.get("aind_hcr_qc_version", "—") if meta else "—"
            else:
                created = "—"
                version = "—"
            meta_rows.append(f"| {mid} | {created} | {version} |")

        # Layout
        if self.layout_mode == "↔ Row":
            container = pn.FlexBox(
                *cards,
                flex_wrap="nowrap",
                gap="10px",
                styles={"overflow-x": "auto"},
            )
        else:
            container = pn.Column(*cards, sizing_mode="stretch_width")

        self._image_area.objects = [container]

        # Metadata table
        table_header = "| Mouse | Created | Version |\n|---|---|---|"
        self._meta_table.object = table_header + "\n" + "\n".join(meta_rows)

    @staticmethod
    def _missing_placeholder(mouse_id: str) -> pn.pane.HTML:
        return pn.pane.HTML(
            '<div style="width:350px;height:250px;background:#e8e8e8;'
            'display:flex;align-items:center;justify-content:center;'
            'color:#999;border-radius:4px">'
            '⚠ Not generated</div>',
        )

    # -- layout pieces for template integration ----------------------------

    def sidebar_widgets(self) -> list:
        """Return widgets to place in the template sidebar."""
        return [
            self._plot_type_select,
            pn.layout.Divider(),
            self._layout_toggle,
            self._hide_missing_cb,
            pn.layout.Divider(),
            pn.pane.Markdown("**Mice**"),
            self._mice_selector,
        ]

    def main_area(self) -> pn.Column:
        """Return the main content area."""
        return pn.Column(
            self._image_area,
            pn.layout.Divider(),
            self._meta_table,
            sizing_mode="stretch_width",
        )

    def __panel__(self):
        return pn.Row(
            pn.Column(*self.sidebar_widgets(), width=230),
            self.main_area(),
            sizing_mode="stretch_both",
        )
