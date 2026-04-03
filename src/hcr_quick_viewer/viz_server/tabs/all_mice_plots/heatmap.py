"""All-mice plot #1 — Gene × Mouse intensity heatmap.

Self-contained: owns its own Panel widgets (metric selector, colormap,
colour-range slider) and exposes two methods for the hosting tab to
compose the layout:

    plot.controls() → pn.Column   (place to the LEFT of the figure)
    plot.plot_panel() → pn.Column (the live Bokeh figure pane)

Square cells
------------
Cell size is fixed at CELL_PX × CELL_PX pixels.  Figure width and height
are computed from the data shape so every cell is a true square regardless
of how many mice or genes are present.
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CELL_PX = 20          # pixel size of each square heatmap cell
LEFT_PAD = 90         # pixels reserved for gene name (y-axis) labels
BOTTOM_PAD = 75       # pixels reserved for mouse ID (x-axis) labels
TOP_PAD = 20          # top whitespace
COLORBAR_PAD = 115    # pixels reserved for the colourbar on the right

_METRIC_OPTIONS: dict[str, str] = {
    "Mean intensity":   "mean_intensity",
    "Median intensity": "median_intensity",
    "Std intensity":    "std_intensity",
    "N spots":          "n_spots",
}

_PALETTE_OPTIONS: dict[str, list] = {
    "Viridis": list(Viridis256),
    "Plasma":  list(Plasma256),
    "Inferno": list(Inferno256),
    "Blues":   list(reversed(Blues256)),
}

# Reverse lookup: column name → display label
_METRIC_LABEL: dict[str, str] = {v: k for k, v in _METRIC_OPTIONS.items()}


# ---------------------------------------------------------------------------
# Plot class
# ---------------------------------------------------------------------------

class HeatmapPlot:
    """Interactive gene × mouse intensity heatmap with inline controls."""

    def __init__(self) -> None:
        self._df: pd.DataFrame = pd.DataFrame()

        # -- widgets -------------------------------------------------------
        self._metric_select = pn.widgets.Select(
            name="Metric",
            options=_METRIC_OPTIONS,   # dict: display label → column name
            value="mean_intensity",
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
            start=0, end=10_000,
            value=(0, 10_000),
            step=10,
            width=200,
        )
        self._reset_btn = pn.widgets.Button(
            name="↺ Reset range", button_type="light", width=130,
        )

        # -- live output containers ----------------------------------------
        self._status = pn.pane.Markdown("", sizing_mode="stretch_width")
        self._plot_pane = pn.Column(sizing_mode="stretch_width")

        # -- wire callbacks ------------------------------------------------
        self._metric_select.param.watch(self._on_metric_change, "value")
        self._palette_select.param.watch(self._on_other_change, "value")
        self._clim_slider.param.watch(self._on_other_change, "value")
        self._reset_btn.on_click(self._on_reset_clim)

    # -- public API --------------------------------------------------------

    def load(self, df: pd.DataFrame) -> None:
        """Supply a new data frame and rebuild the figure."""
        self._df = df
        self._reset_clim_to_data()
        self._rebuild()

    def controls(self) -> pn.Column:
        """Sidebar-style control column to place beside the figure."""
        return pn.Column(
            pn.pane.Markdown("### Controls", margin=(0, 0, 6, 0)),
            self._metric_select,
            pn.layout.Divider(),
            self._palette_select,
            pn.layout.Divider(),
            pn.pane.Markdown("**Color range**", margin=(0, 0, 2, 0)),
            self._clim_slider,
            self._reset_btn,
            width=230,
            margin=(8, 20, 0, 0),
        )

    def plot_panel(self) -> pn.Column:
        """Container that holds the live Bokeh figure."""
        return pn.Column(
            self._status,
            self._plot_pane,
            scroll=True,            # horizontal scroll when figure exceeds viewport
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
        return float(vals.min()), float(vals.max())

    def _reset_clim_to_data(self) -> None:
        vmin, vmax = self._data_range()
        span = vmax - vmin if vmax > vmin else 1.0
        step = max(0.1, round(span / 200, 1))
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
        # _clim_slider param.watch triggers _rebuild automatically

    # -- figure construction -----------------------------------------------

    def _rebuild(self) -> None:
        metric = self._metric_select.value

        if self._df.empty or metric not in self._df.columns:
            msg = (
                "*No metrics found in `scratch/metrics/`. "
                "Run `run_capsule.py` for each mouse to generate them.*"
                if self._df.empty
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

        # -- pivot ---------------------------------------------------------
        pivot = self._df.pivot(index="gene", columns="mouse_id", values=metric)
        genes = sorted(pivot.index.tolist())
        mice = sorted(pivot.columns.tolist())
        pivot = pivot.loc[genes, mice]

        df_melt = (
            pivot.reset_index()
            .melt(id_vars="gene", var_name="mouse_id", value_name="value")
        )
        df_melt["value_str"] = df_melt["value"].apply(
            lambda v: f"{v:,.1f}" if pd.notna(v) else "N/A"
        )
        source = ColumnDataSource(df_melt)

        # -- colour mapper --------------------------------------------------
        mapper = LinearColorMapper(
            palette=palette,
            low=vmin,
            high=vmax,
            nan_color="#e0e0e0",
        )

        # -- figure with square cells (fixed pixel dimensions) -------------
        n_genes = len(genes)
        n_mice = len(mice)
        fig_h = n_genes * CELL_PX + BOTTOM_PAD + TOP_PAD
        fig_w = n_mice * CELL_PX + LEFT_PAD + COLORBAR_PAD

        p = figure(
            x_range=mice,
            y_range=list(reversed(genes)),   # alphabetical top-to-bottom
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

        # -- hover tooltip -------------------------------------------------
        metric_label = _METRIC_LABEL.get(metric, metric)
        hover = p.select_one(HoverTool)
        hover.tooltips = [
            ("Mouse",      "@mouse_id"),
            ("Gene",       "@gene"),
            (metric_label, "@value_str"),
        ]

        # -- colour bar ----------------------------------------------------
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

        # -- axis styling --------------------------------------------------
        p.axis.major_label_text_font_size = "10px"
        p.xaxis.major_label_orientation = 1.1   # ~63°
        p.xgrid.grid_line_color = None
        p.ygrid.grid_line_color = None
        p.background_fill_color = "#fafafa"
        p.outline_line_color = None

        self._plot_pane.objects = [pn.pane.Bokeh(p, sizing_mode="fixed")]
