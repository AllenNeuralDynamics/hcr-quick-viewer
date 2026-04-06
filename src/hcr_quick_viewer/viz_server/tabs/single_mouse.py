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
            title="Plot Details",
            collapsed=True,
            sizing_mode="stretch_width",
        )

        # -- neuroglancer links content (lives in the NG tab) -------------
        self._ng_links_content = pn.pane.HTML("", sizing_mode="stretch_width")

        # -- round plots state -------------------------------------------
        self._rounds_main_col = pn.Column(sizing_mode="stretch_width")
        self._round_full_img_pane = pn.pane.PNG(
            object=None, sizing_mode="scale_width", max_width=1200,
        )
        self._round_meta_strip = pn.pane.Markdown("", sizing_mode="stretch_width")

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
                self._rebuild_rounds_grid()

    # -- callbacks ---------------------------------------------------------

    def _on_mouse_change(self, event) -> None:
        self.mouse_id = event.new
        self._rebuild_grid()
        self._rebuild_ng_links()
        self._rebuild_rounds_grid()

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
            '<table style="border-collapse:collapse;'
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

    # ---- round-plots tab -----------------------------------------------

    _ROUND_THUMB_PLOT = "tile_overview_ch405"

    def _rebuild_rounds_grid(self) -> None:
        """Build the top-level round card grid (one card per processed asset)."""
        round_catalog = catalog.load_round_catalog(self.mouse_id)

        if not round_catalog:
            self._rounds_main_col.objects = [
                pn.pane.HTML(
                    '<span style="color:#999;font-style:italic">'
                    "No round-specific QC plots found.</span>",
                    sizing_mode="stretch_width",
                )
            ]
            return

        cards = []
        for asset_name, plot_types in round_catalog.items():
            # Load sidecar of the tile-overview plot to get round_label / gene info
            thumb_plot = (
                self._ROUND_THUMB_PLOT
                if self._ROUND_THUMB_PLOT in plot_types
                else plot_types[0]
            )
            meta = catalog.load_round_plot_metadata(
                self.mouse_id, asset_name, thumb_plot
            )
            round_label = (meta or {}).get("round_label", "")
            gene_dict = (meta or {}).get("gene_dict", {})

            # Build a short display title from the acquisition date in the asset name
            # e.g. HCR_755252_2025-07-10_13-00-00_processed_... → "R2: 2025-07-10"
            parts = asset_name.split("_")
            try:
                acq_date = parts[2]          # YYYY-MM-DD
                acq_time = parts[3].replace("-", ":")[:5]  # HH:MM
                short_title = f"{acq_date}  {acq_time}"
            except IndexError:
                short_title = asset_name
            display_title = f"{round_label}: {short_title}" if round_label else short_title

            thumb_bytes = image_cache.get_round_thumbnail_bytes(
                self.mouse_id, asset_name, thumb_plot
            )
            if thumb_bytes:
                thumb_pane = pn.pane.PNG(
                    object=BytesIO(thumb_bytes), width=180, height=140,
                    sizing_mode="fixed",
                )
            else:
                thumb_pane = pn.pane.HTML(
                    '<div style="width:180px;height:140px;background:#dde;'
                    'display:flex;align-items:center;justify-content:center;'
                    f'color:#99a;font-size:{FONT_SIZE["xs"]}">no preview</div>',
                )

            click_btn = pn.widgets.Button(
                name="", width=190, height=150, button_type="light",
                stylesheets=[
                    ":host { position: absolute; top: 0; left: 0; z-index: 1; }"
                    ":host .bk-btn { background: transparent; border: none; "
                    "cursor: pointer; width: 100%; height: 100%; }"
                ],
            )
            click_btn.on_click(
                lambda _e, _an=asset_name, _pts=plot_types:
                    self._show_round_detail(_an, _pts)
            )

            thumb_wrapper = pn.Column(
                thumb_pane, click_btn,
                styles={"position": "relative"},
                width=190, height=150,
            )

            header_html = pn.pane.HTML(
                f'<div style="font-size:{FONT_SIZE["card_label"]};font-weight:600;'
                f'padding:4px 2px;word-break:break-word">{display_title}</div>'
                f'<div style="font-size:{FONT_SIZE["xs"]};color:#666;padding:0 2px 4px">'
                f'{len(plot_types)} plot{"s" if len(plot_types) != 1 else ""}</div>',
                sizing_mode="stretch_width",
            )

            # --- channel : gene footer (max 6 genes shown) ---
            _CARD_HEIGHT = 430
            if gene_dict:
                sorted_genes = sorted(
                    gene_dict.items(),
                    key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0,
                )[:6]
                gene_lines = "".join(
                    f'<div style="display:flex;gap:6px;line-height:1.5">'
                    f'<span style="min-width:36px;text-align:right;color:#555">{ch}</span>'
                    f'<span style="color:#aaa">–</span>'
                    f'<span style="color:#333">'
                    f'{info.get("gene","") if isinstance(info,dict) else info}'
                    f'</span></div>'
                    for ch, info in sorted_genes
                )
                footer_html = pn.pane.HTML(
                    f'<div style="padding:6px 4px 4px;border-top:1px solid #dde;margin-top:4px">'
                    f'<div style="font-weight:700;font-size:{FONT_SIZE["xs"]};'
                    f'margin-bottom:3px">{round_label}</div>'
                    f'<div style="font-size:{FONT_SIZE["xs"]};font-family:monospace">'
                    + gene_lines +
                    f'</div></div>',
                    sizing_mode="stretch_width",
                )
                card_body = pn.Column(header_html, thumb_wrapper, footer_html, width=200)
            else:
                card_body = pn.Column(header_html, thumb_wrapper, width=200)

            card = pn.Card(
                card_body,
                width=210, height=_CARD_HEIGHT,
                styles={"background": "#f4f4fb"},
                hide_header=True,
            )
            cards.append(card)

        grid = pn.FlexBox(*cards, flex_wrap="wrap", align_items="start", gap="12px")
        self._rounds_main_col.objects = [grid]

    def _show_round_detail(self, asset_name: str, plot_types: list[str]) -> None:
        """Switch to the detail view for a specific round (all plots + full viewer)."""
        # Prefetch thumbnails in parallel
        thumbs = image_cache.prefetch_round_thumbnails(
            self.mouse_id, asset_name, plot_types
        )

        # Load sidecar for metadata (prefer tile_overview)
        thumb_plot = (
            self._ROUND_THUMB_PLOT
            if self._ROUND_THUMB_PLOT in plot_types
            else plot_types[0]
        )
        meta = catalog.load_round_plot_metadata(self.mouse_id, asset_name, thumb_plot)

        round_label = (meta or {}).get("round_label", "")
        source_assets = (meta or {}).get("source_assets", {})
        raw_name = source_assets.get("raw", "")
        gene_dict = (meta or {}).get("gene_dict", {})

        # --- channel:gene table ---
        if gene_dict:
            gene_rows = "".join(
                f'<tr>'
                f'<td style="padding:2px 14px 2px 4px;font-weight:600;color:#333">{ch} nm</td>'
                f'<td style="padding:2px 4px;color:#555">'
                f'{info.get("gene", "") if isinstance(info, dict) else info}</td>'
                f'</tr>'
                for ch, info in sorted(
                    gene_dict.items(),
                    key=lambda x: int(x[0]) if x[0].isdigit() else 0,
                )
            )
            gene_table = (
                f'<table style="border-collapse:collapse;font-size:{FONT_SIZE["sm"]};'
                'margin:6px 0 10px">'
                '<thead><tr>'
                '<th style="text-align:left;padding:2px 14px 2px 4px;'
                'border-bottom:1px solid #ddd">Channel</th>'
                '<th style="text-align:left;padding:2px 4px;'
                'border-bottom:1px solid #ddd">Gene</th>'
                '</tr></thead><tbody>' + gene_rows + '</tbody></table>'
            )
        else:
            gene_table = ""

        title_text = f"{round_label}: {asset_name}" if round_label else asset_name
        raw_line = (
            f'<div style="font-size:{FONT_SIZE["xs"]};color:#666;margin-bottom:4px">'
            f'Raw: <code style="font-size:0.85em">{raw_name}</code></div>'
            if raw_name else ""
        )
        header_pane = pn.pane.HTML(
            f'<h3 style="margin:0 0 2px;font-size:{FONT_SIZE["header"]}">{title_text}</h3>'
            + raw_line + gene_table,
            sizing_mode="stretch_width",
        )

        back_btn = pn.widgets.Button(
            name="← Back to rounds", width=160, button_type="light"
        )
        back_btn.on_click(lambda _e: self._rebuild_rounds_grid())

        # --- thumbnail grid ---
        thumb_cards = []
        for pt in plot_types:
            label = pt.replace("_", " ")
            thumb_bytes = thumbs.get(pt)

            if thumb_bytes:
                t_pane = pn.pane.PNG(
                    object=BytesIO(thumb_bytes), width=180, height=130,
                    sizing_mode="fixed",
                )
            else:
                t_pane = pn.pane.HTML(
                    '<div style="width:180px;height:130px;background:#eee;'
                    'display:flex;align-items:center;justify-content:center;'
                    f'color:#bbb;font-size:{FONT_SIZE["xs"]}">loading…</div>',
                )

            t_btn = pn.widgets.Button(
                name="", width=190, height=140, button_type="light",
                stylesheets=[
                    ":host { position: absolute; top: 0; left: 0; z-index: 1; }"
                    ":host .bk-btn { background: transparent; border: none; "
                    "cursor: pointer; width: 100%; height: 100%; }"
                ],
            )
            t_btn.on_click(
                lambda _e, _an=asset_name, _pt=pt:
                    self._show_round_plot(_an, _pt)
            )
            t_wrapper = pn.Column(
                t_pane, t_btn,
                styles={"position": "relative"},
                width=190, height=140,
            )
            t_header = pn.pane.HTML(
                f'<span style="font-size:{FONT_SIZE["xs"]};color:#444">{label}</span>',
                sizing_mode="stretch_width",
            )
            thumb_cards.append(
                pn.Card(
                    pn.Column(t_header, t_wrapper, width=200),
                    width=210, height=205,
                    styles={"background": "#f9f9f9"},
                    hide_header=True,
                )
            )

        # Reset full-size viewer when entering detail view
        self._round_full_img_pane.object = None
        self._round_meta_strip.object = ""

        self._rounds_main_col.objects = [
            pn.Row(back_btn),
            header_pane,
            pn.layout.Divider(),
            pn.FlexBox(*thumb_cards, flex_wrap="wrap", align_items="start", gap="10px"),
            pn.layout.Divider(),
            self._round_full_img_pane,
            self._round_meta_strip,
        ]

    def _show_round_plot(self, asset_name: str, plot_type: str) -> None:
        """Load and display a full-size round-level plot."""
        data = image_cache.get_round_plot_bytes(self.mouse_id, asset_name, plot_type)
        if data is None:
            self._round_full_img_pane.object = None
            self._round_meta_strip.object = "*Image not available.*"
            return
        self._round_full_img_pane.object = BytesIO(data)
        meta = catalog.load_round_plot_metadata(self.mouse_id, asset_name, plot_type)
        if meta:
            created = meta.get("created_at", "?")
            version = meta.get("aind_hcr_qc_version", "?")
            label = plot_type.replace("_", " ")
            self._round_meta_strip.object = (
                f"*{label} · created {created} · v{version}*"
            )
        else:
            self._round_meta_strip.object = ""

    # ---- end round-plots tab -------------------------------------------

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

                card_content = pn.Column(header, thumb_wrapper, width=200)
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
        thumbnails_card = pn.Card(
            self._plot_grid,
            title="Thumbnails",
            collapsed=False,
            sizing_mode="stretch_width",
        )
        qc_plots_col = pn.Column(
            thumbnails_card,
            pn.layout.Divider(),
            self._image_pane,
            self._metadata_strip,
            self._metadata_details,
            sizing_mode="stretch_width",
        )
        inner_tabs = pn.Tabs(
            ("Integrated Plots", qc_plots_col),
            ("Round Plots", self._rounds_main_col),
            ("Neuroglancer Links", pn.Column(self._ng_links_content, sizing_mode="stretch_width")),
            dynamic=True,
            sizing_mode="stretch_width",
        )
        return pn.Column(
            inner_tabs,
            sizing_mode="stretch_width",
        )

    def __panel__(self):
        return pn.Row(
            pn.Column(*self.sidebar_widgets(), width=300),
            self.main_area(),
            sizing_mode="stretch_both",
        )
