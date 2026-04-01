"""Tab 1 – Single Mouse view.

Shows all known plot types for one selected mouse, with ✓/⚠ badges for
availability, a full-size image viewer, and collapsible metadata.
"""

from __future__ import annotations

from io import BytesIO

import panel as pn
import param

from hcr_quick_viewer.viz_server import catalog, image_cache
from hcr_quick_viewer.viz_server.theme import FONT_SIZE


class SingleMouseTab(pn.viewable.Viewer):
    """Single-mouse QC viewer tab."""

    mouse_id = param.String(default="", doc="Currently selected mouse ID")
    fmt = param.Selector(default="PNG", objects=["PNG", "PDF"], doc="Image format")
    selected_plot = param.String(default="", doc="Currently selected plot type")

    def __init__(self, **params):
        super().__init__(**params)

        self._mouse_select = pn.widgets.Select(
            name="Mouse", options=[], width=200,
        )
        self._format_radio = pn.widgets.RadioButtonGroup(
            name="Format", options=["PNG", "PDF"], value="PNG", width=200,
        )
        self._plot_grid = pn.FlexBox(
            flex_wrap="wrap", align_items="start", gap="10px",
        )
        self._image_pane = pn.pane.PNG(
            object=None, sizing_mode="scale_width", max_width=1200,
        )
        self._metadata_strip = pn.pane.Markdown("", sizing_mode="stretch_width")
        self._metadata_details = pn.Card(
            pn.pane.JSON({}, depth=3, name="sidecar"),
            title="Details",
            collapsed=True,
            sizing_mode="stretch_width",
        )

        # -- neuroglancer links card --------------------------------------
        self._ng_links_content = pn.pane.HTML("", sizing_mode="stretch_width")
        self._ng_links_card = pn.Card(
            self._ng_links_content,
            title="Neuroglancer Links",
            collapsed=True,
            sizing_mode="stretch_width",
        )

        # -- keyboard nav bridge ------------------------------------------
        # Hidden IntInput whose value is changed by JS keydown listener.
        # Odd increments = "next", even decrements = "prev".  We just watch
        # for *any* change and inspect the direction.
        self._keynav = pn.widgets.IntInput(
            value=0, visible=False, tags=["hcr-keynav"],
        )
        self._keynav.param.watch(self._on_keynav, "value")

        # Prev / Next buttons
        self._prev_btn = pn.widgets.Button(name="← Prev", width=90)
        self._next_btn = pn.widgets.Button(name="Next →", width=90)
        self._prev_btn.on_click(lambda e: self._step_plot(-1))
        self._next_btn.on_click(lambda e: self._step_plot(1))

        # Track the ordered list of *available* plot types for stepping
        self._available_plot_types: list[str] = []

        # -- category filter ----------------------------------------------
        self._category_filter = pn.widgets.CheckButtonGroup(
            name="Categories",
            options=[],   # populated on first reload
            value=[],     # all selected by default (set in reload)
            button_type="default",
            orientation="vertical",
            width=200,
            stylesheets=[
                ":host .bk-btn-group .bk-btn { "
                "  font-size: 0.85rem !important; padding: 4px 10px !important; "
                "  border: 1px solid #ccc !important; border-radius: 4px !important; "
                "  background: #e8e8e8 !important; color: #888 !important; "
                "} "
                ":host .bk-btn-group .bk-btn.bk-active { "
                "  background: #2b579a !important; color: #fff !important; "
                "  border-color: #2b579a !important; font-weight: 600 !important; "
                "} "
            ],
        )
        self._category_filter.param.watch(self._on_category_change, "value")

        self._mouse_select.param.watch(self._on_mouse_change, "value")
        self._format_radio.param.watch(self._on_format_change, "value")

    # -- public API --------------------------------------------------------

    @staticmethod
    def _category_of(plot_type: str) -> str:
        """Extract the category prefix from a plot type name."""
        return plot_type.split("_", 1)[0]

    def reload(self) -> None:
        """Refresh catalog data and rebuild the widget."""
        cat = catalog.load_catalog()
        mice = catalog.mice_in_catalog(cat)
        self._mouse_select.options = mice

        # Discover all categories from the full catalog
        all_types = catalog.known_plot_types(cat)
        categories = sorted({self._category_of(pt) for pt in all_types})
        prev_value = self._category_filter.value
        self._category_filter.options = categories
        # Keep previous selection if still valid, otherwise select all
        valid = [c for c in prev_value if c in categories]
        self._category_filter.value = valid if valid else categories

        if mice:
            if self._mouse_select.value not in mice:
                self._mouse_select.value = mice[0]
            else:
                # Trigger rebuild even if value didn't change
                self._rebuild_grid()
                self._rebuild_ng_links()

    # -- callbacks ---------------------------------------------------------

    def _on_mouse_change(self, event) -> None:
        self.mouse_id = event.new
        self._rebuild_grid()
        self._rebuild_ng_links()

    def _on_format_change(self, event) -> None:
        self.fmt = event.new
        if self.selected_plot:
            self._show_plot(self.selected_plot)

    def _on_category_change(self, event) -> None:
        """Re-filter the grid when category selection changes."""
        self._rebuild_grid()

    def _on_keynav(self, event) -> None:
        """Called when the hidden IntInput changes via JS key listener."""
        # JS increments for → and decrements for ←
        direction = 1 if event.new > event.old else -1
        self._step_plot(direction)

    def _step_plot(self, direction: int) -> None:
        """Move to the previous (-1) or next (+1) available plot."""
        if not self._available_plot_types:
            return
        if not self.selected_plot:
            # Nothing selected yet — pick the first
            self._on_card_click(self._available_plot_types[0])
            return
        try:
            idx = self._available_plot_types.index(self.selected_plot)
        except ValueError:
            idx = 0
        new_idx = (idx + direction) % len(self._available_plot_types)
        self._on_card_click(self._available_plot_types[new_idx])

    def _rebuild_ng_links(self) -> None:
        """Fetch and render the neuroglancer links table for the current mouse."""
        data = catalog.load_ng_links(self.mouse_id)
        if not data or not data.get("rounds"):
            self._ng_links_content.object = (
                '<span style="color:#999;font-style:italic">No neuroglancer links found.</span>'
            )
            return

        rows_html = []
        for round_label, links in sorted(data["rounds"].items()):
            # Exclude cross-channel comparison links from the display
            display_links = [lnk for lnk in links if not lnk["name"].startswith("cc_ng")]
            if not display_links:
                continue
            for i, lnk in enumerate(display_links):
                round_cell = (
                    f'<td rowspan="{len(display_links)}" style="'
                    'font-weight:bold;vertical-align:top;padding:4px 12px 4px 4px;'
                    f'white-space:nowrap">{round_label}</td>'
                    if i == 0
                    else ""
                )
                name = lnk["name"].replace("_", " ")
                url = lnk["url"]
                rows_html.append(
                    f"<tr>{round_cell}"
                    f'<td style="padding:4px 12px">{name}</td>'
                    f'<td style="padding:4px">'
                    f'<a href="{url}" target="_blank" '
                    f'style="color:#2b579a;text-decoration:none;font-weight:600">'
                    f"Open ↗</a></td></tr>"
                )

        if not rows_html:
            self._ng_links_content.object = (
                '<span style="color:#999;font-style:italic">No neuroglancer links found.</span>'
            )
            return

        table = (
            '<table style="border-collapse:collapse;width:100%;'
            f'font-size:{FONT_SIZE["sm"]}">'
            '<thead><tr>'
            '<th style="text-align:left;padding:4px 12px 4px 4px;border-bottom:1px solid #ddd">Round</th>'
            '<th style="text-align:left;padding:4px 12px;border-bottom:1px solid #ddd">Link</th>'
            '<th style="border-bottom:1px solid #ddd"></th>'
            "</tr></thead><tbody>"
            + "".join(rows_html)
            + "</tbody></table>"
        )
        self._ng_links_content.object = table

    def _rebuild_grid(self) -> None:
        """Rebuild the plot-type card grid for the current mouse."""
        cat = catalog.load_catalog()
        all_types = catalog.known_plot_types(cat)
        mouse_types = set(catalog.plot_types_for_mouse(cat, self.mouse_id))

        # Filter by selected categories
        selected_cats = set(self._category_filter.value)
        all_types = [pt for pt in all_types if self._category_of(pt) in selected_cats]

        # Prefetch all thumbnails in parallel
        available_types = [pt for pt in all_types if pt in mouse_types]
        self._available_plot_types = available_types
        thumbs = image_cache.prefetch_thumbnails(self.mouse_id, available_types)

        cards = []
        for pt in all_types:
            available = pt in mouse_types
            badge = "✓" if available else "⚠"
            badge_color = "#2ecc71" if available else "#e67e22"

            label = pt.replace("_", " ")
            header = pn.pane.HTML(
                f'<span style="color:{badge_color};font-weight:bold">{badge}</span> '
                f'<span style="font-size:{FONT_SIZE["card_label"]}">{label}</span>',
                sizing_mode="stretch_width",
            )

            if available:
                has_pdf_flag = catalog.has_pdf(cat, self.mouse_id, pt)
                links = "[PNG]"
                if has_pdf_flag:
                    links += " [PDF]"
                link_row = pn.pane.HTML(
                    f'<span style="font-size:{FONT_SIZE["xs"]};color:#888">{links}</span>',
                )

                # Thumbnail from prefetch cache
                thumb_bytes = thumbs.get(pt)
                if thumb_bytes:
                    thumb_pane = pn.pane.PNG(
                        object=BytesIO(thumb_bytes),
                        width=180, height=120,
                        sizing_mode="fixed",
                    )
                else:
                    thumb_pane = pn.pane.HTML(
                        '<div style="width:180px;height:120px;background:#eee;'
                        'display:flex;align-items:center;justify-content:center;'
                        f'color:#bbb;font-size:{FONT_SIZE["xs"]}">loading…</div>',
                    )

                # Transparent click overlay on top of the thumbnail
                click_btn = pn.widgets.Button(
                    name="", width=190, height=130,
                    button_type="light",
                    stylesheets=[
                        ":host { position: absolute; top: 0; left: 0; z-index: 1; }"
                        ":host .bk-btn { background: transparent; border: none; "
                        "cursor: pointer; width: 100%; height: 100%; }"
                    ],
                )
                click_btn.on_click(lambda event, _pt=pt: self._on_card_click(_pt))

                thumb_wrapper = pn.Column(
                    thumb_pane, click_btn,
                    styles={"position": "relative"},
                    width=200, height=130,
                )

                card_content = pn.Column(header, thumb_wrapper, link_row, width=200)
            else:
                missing = pn.pane.HTML(
                    f'<span style="font-size:{FONT_SIZE["xs"]};color:#999">not generated</span>',
                )
                card_content = pn.Column(header, missing, width=200)

            card = pn.Card(
                card_content,
                width=210,
                height=220 if available else 100,
                styles={"background": "#f9f9f9" if available else "#f0f0f0"},
                hide_header=True,
            )
            cards.append(card)

        self._plot_grid.objects = cards

        # Clear viewer when switching mice
        self.selected_plot = ""
        self._image_pane.object = None
        self._metadata_strip.object = ""
        self._metadata_details[0].object = {}

    def _on_card_click(self, plot_type: str) -> None:
        self.selected_plot = plot_type
        self._show_plot(plot_type)

    def _show_plot(self, plot_type: str) -> None:
        """Load and display the selected plot + metadata."""
        fmt = self.fmt.lower()
        data = image_cache.get_plot_bytes(self.mouse_id, plot_type, fmt=fmt)

        if data is None:
            self._image_pane.object = None
            self._metadata_strip.object = f"*No {fmt.upper()} available for this plot.*"
            return

        if fmt == "png":
            self._image_pane.object = BytesIO(data)
        else:
            # PDF: offer as download rather than inline render
            self._image_pane.object = None
            self._metadata_strip.object = (
                "*PDF loaded — use the download button below.*"
            )

        # Metadata
        meta = catalog.load_plot_metadata(self.mouse_id, plot_type)
        if meta:
            created = meta.get("created_at", "?")
            version = meta.get("aind_hcr_qc_version", "?")
            kwargs = meta.get("plot_kwargs", {})
            kwargs_str = ", ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
            summary = f"created {created}"
            if version != "?":
                summary += f" · v{version}"
            if kwargs_str:
                summary += f" · {kwargs_str}"
            self._metadata_strip.object = f"*{summary}*"
            self._metadata_details[0].object = meta
        else:
            self._metadata_strip.object = ""
            self._metadata_details[0].object = {}

    # -- layout pieces for template integration ----------------------------

    def sidebar_widgets(self) -> list:
        """Return widgets to place in the template sidebar."""
        nav_row = pn.Row(self._prev_btn, self._next_btn, width=200)
        hotkey_hint = pn.pane.HTML(
            '<span style="font-size:0.8rem;color:#888">← → arrow keys to flip plots</span>',
        )
        return [
            self._mouse_select,
            pn.layout.Divider(),
            pn.pane.HTML(
                '<div style="text-align:center;font-weight:bold">Categories</div>',
                width=200,
            ),
            self._category_filter,
            pn.layout.Divider(),
            nav_row,
            hotkey_hint,
            self._keynav,  # hidden — JS bridge
        ]

    def main_area(self) -> pn.Column:
        """Return the main content area."""
        return pn.Column(
            self._plot_grid,
            pn.layout.Divider(),
            self._ng_links_card,
            pn.layout.Divider(),
            self._image_pane,
            self._metadata_strip,
            self._metadata_details,
            sizing_mode="stretch_width",
        )

    def __panel__(self):
        return pn.Row(
            pn.Column(*self.sidebar_widgets(), width=300),
            self.main_area(),
            sizing_mode="stretch_both",
        )
