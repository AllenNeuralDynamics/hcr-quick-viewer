"""All-mice plot #2 — Gene × Mouse normalized-counts heatmap.

Shows mean (or median) CPM-normalized spot counts per gene per mouse.
Supports the same log₁₀ toggle, colormap, and colour-range controls as the
intensity heatmap.  Follows the same controls()/plot_panel() contract so the
AllMiceTab can swap it in without any layout changes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import panel as pn
from bokeh.models import (
    BasicTicker,
    ColorBar,
    ColumnDataSource,
    HoverTool,
    LinearColorMapper,
)
from bokeh.palettes import Blues256, Inferno256, Plasma256, Viridis256
from bokeh.plotting import figure
from bokeh.transform import transform

# Re-use the same cell-size constants as the intensity heatmap
CELL_PX = 20
LEFT_PAD = 90
BOTTOM_PAD = 75
TOP_PAD = 20
COLORBAR_PAD = 115

_METRIC_OPTIONS: dict[str, str] = {
    "Mean normalized counts":   "mean_normalized_counts",
    "Median normalized counts": "median_normalized_counts",
}

_PALETTE_OPTIONS: dict[str, list] = {
    "Viridis": list(Viridis256),
    "Plasma":  list(Plasma256),
    "Inferno": list(Inferno256),
    "Blues":   list(reversed(Blues256)),
}

_METRIC_LABEL: dict[str, str] = {v: k for k, v in _METRIC_OPTIONS.items()}


class NormalizedCountsPlot:
    """Interactive gene × mouse normalized-counts heatmap."""

    def __init__(self) -> None:
        self._df: pd.DataFrame = pd.DataFrame()

        self._metric_select = pn.widgets.Select(
            name="Metric",
            options=_METRIC_OPTIONS,
            value="mean_normalized_counts",
            width=200,
        )
        self._palette_select = pn.widgets.Select(
            name="Colormap",
            options=list(_PALETTE_OPTIONS.keys()),
            value="Viridis",
            width=200,
        )
        self._clim_slider = pn.widgets.RangeSlider(
            name="Color range",
            start=0, end=1_000,
            value=(0, 1_000),
            step=1,
            width=200,
        )
        self._reset_btn = pn.widgets.Button(
            name="↺ Reset range", button_type="light", width=130,
        )
        self._log_toggle = pn.widgets.Toggle(
            name="Log₁₀ scale", value=False, button_type="default", width=130,
        )

        self._status = pn.pane.Markdown("", sizing_mode="stretch_width")
        self._plot_pane = pn.Column(sizing_mode="stretch_width")

        self._metric_select.param.watch(self._on_metric_change, "value")
        self._palette_select.param.watch(self._on_other_change, "value")
        self._clim_slider.param.watch(self._on_other_change, "value")
        self._reset_btn.on_click(self._on_reset_clim)
        self._log_toggle.param.watch(self._on_log_change, "value")

    # -- public API --------------------------------------------------------

    def load(self, df: pd.DataFrame) -> None:
        self._df = df
        self._reset_clim_to_data()
        self._rebuild()

    def controls(self) -> pn.Column:
        return pn.Column(
            pn.pane.Markdown("### Controls", margin=(0, 0, 6, 0)),
            pn.pane.Markdown(
                "*Counts normalized to total spots per cell × 1000 (CPM-style)*",
                styles={"font-size": "0.82rem", "color": "#666"},
                margin=(0, 0, 8, 0),
            ),
            self._metric_select,
            pn.layout.Divider(),
            self._palette_select,
            pn.layout.Divider(),
            pn.pane.Markdown("**Color range**", margin=(0, 0, 2, 0)),
            self._clim_slider,
            self._reset_btn,
            pn.layout.Divider(),
            self._log_toggle,
            width=230,
            margin=(8, 20, 0, 0),
        )

    def plot_panel(self) -> pn.Column:
        return pn.Column(
            self._status,
            self._plot_pane,
            scroll=True,
            sizing_mode="stretch_width",
        )

    # -- helpers -----------------------------------------------------------

    def _data_range(self) -> tuple[float, float]:
        metric = self._metric_select.value
        if self._df.empty or metric not in self._df.columns:
            return 0.0, 1.0
        vals = self._df[metric].dropna()
        if vals.empty:
            return 0.0, 1.0
        if self._log_toggle.value:
            vals = np.log10(vals.clip(lower=1e-9))
        return float(vals.min()), float(vals.max())

    def _reset_clim_to_data(self) -> None:
        vmin, vmax = self._data_range()
        span = vmax - vmin if vmax > vmin else 1.0
        step = max(0.01, round(span / 200, 3))
        self._clim_slider.param.update(
            start=vmin, end=vmax, step=step, value=(vmin, vmax),
        )

    # -- callbacks ---------------------------------------------------------

    def _on_metric_change(self, event) -> None:
        self._reset_clim_to_data()
        self._rebuild()

    def _on_other_change(self, event) -> None:
        self._rebuild()

    def _on_reset_clim(self, event) -> None:
        self._reset_clim_to_data()

    def _on_log_change(self, event) -> None:
        self._reset_clim_to_data()
        self._rebuild()

    # -- figure construction -----------------------------------------------

    def _rebuild(self) -> None:
        metric = self._metric_select.value

        if self._df.empty or metric not in self._df.columns:
            msg = (
                "*No normalized-count metrics found. "
                "Re-run `run_capsule.py` for each mouse to generate them.*"
                if self._df.empty or "mean_normalized_counts" not in self._df.columns
                else f"*Metric `{metric}` not yet present in the data.*"
            )
            self._status.object = msg
            self._plot_pane.objects = []
            return

        self._status.object = ""

        palette = _PALETTE_OPTIONS[self._palette_select.value]
        vmin, vmax = self._clim_slider.value
        if vmax <= vmin:
            vmax = vmin + 1.0

        pivot = self._df.pivot_table(
            index="gene", columns="mouse_id", values=metric, aggfunc="mean"
        )
        genes = sorted(pivot.index.tolist())
        mice = sorted(pivot.columns.tolist())
        pivot = pivot.loc[genes, mice]

        if self._log_toggle.value:
            display_pivot = np.log10(pivot.clip(lower=1e-9).where(pivot.notna()))
        else:
            display_pivot = pivot

        df_melt = (
            display_pivot.reset_index()
            .melt(id_vars="gene", var_name="mouse_id", value_name="value")
        )
        raw_melt = (
            pivot.reset_index()
            .melt(id_vars="gene", var_name="mouse_id", value_name="raw_value")
        )
        df_melt["raw_value"] = raw_melt["raw_value"]
        df_melt["value_str"] = df_melt.apply(
            lambda r: (
                f"{r['raw_value']:,.2f} (log₁₀: {r['value']:.3f})"
                if self._log_toggle.value and pd.notna(r["raw_value"])
                else (f"{r['raw_value']:,.2f}" if pd.notna(r["raw_value"]) else "N/A")
            ),
            axis=1,
        )
        source = ColumnDataSource(df_melt)

        mapper = LinearColorMapper(
            palette=palette,
            low=vmin,
            high=vmax,
            nan_color="#e0e0e0",
        )

        n_genes = len(genes)
        n_mice = len(mice)
        fig_h = n_genes * CELL_PX + BOTTOM_PAD + TOP_PAD
        fig_w = n_mice * CELL_PX + LEFT_PAD + COLORBAR_PAD

        p = figure(
            x_range=mice,
            y_range=list(reversed(genes)),
            width=fig_w,
            height=fig_h,
            toolbar_location="right",
            tools="hover,pan,wheel_zoom,reset,save",
        )

        p.rect(
            x="mouse_id",
            y="gene",
            width=0.95,
            height=0.95,
            source=source,
            fill_color=transform("value", mapper),
            line_color=None,
        )

        metric_label = _METRIC_LABEL.get(metric, metric)
        if self._log_toggle.value:
            metric_label = f"log₁₀({metric_label})"

        hover = p.select_one(HoverTool)
        hover.tooltips = [
            ("Mouse",      "@mouse_id"),
            ("Gene",       "@gene"),
            (metric_label, "@value_str"),
        ]

        color_bar = ColorBar(
            color_mapper=mapper,
            ticker=BasicTicker(desired_num_ticks=8),
            label_standoff=8,
            border_line_color=None,
            location=(0, 0),
            title=metric_label,
            title_text_font_size="11px",
            major_label_text_font_size="10px",
            width=14,
        )
        p.add_layout(color_bar, "right")

        p.axis.major_label_text_font_size = "10px"
        p.xaxis.major_label_orientation = 1.1
        p.xgrid.grid_line_color = None
        p.ygrid.grid_line_color = None
        p.background_fill_color = "#fafafa"
        p.outline_line_color = None

        self._plot_pane.objects = [pn.pane.Bokeh(p, sizing_mode="fixed")]
