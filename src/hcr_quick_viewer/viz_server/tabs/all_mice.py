"""Tab 3 – All Mice view.

A dropdown at the top of the app sidebar selects which interactive plot to
display.  Each plot lives in its own module under ``all_mice_plots/`` and
exposes two methods:

    plot.controls()    → pn.Column  – controls placed LEFT of the figure
    plot.plot_panel()  → pn.Column  – the reactive Bokeh figure pane

Adding a new plot
-----------------
1. Create ``tabs/all_mice_plots/my_plot.py`` with a class that implements
   ``load(df)``, ``controls()``, and ``plot_panel()``.
2. Add it to ``_PLOT_REGISTRY`` below.
"""

from __future__ import annotations

import json

import boto3
from botocore.exceptions import ClientError
import pandas as pd
import panel as pn
import param

from hcr_quick_viewer.viz_server.tabs.all_mice_plots.heatmap import HeatmapPlot
from hcr_quick_viewer.viz_server.tabs.all_mice_plots.normalized_counts import NormalizedCountsPlot

METRICS_S3_BUCKET: str = "aind-scratch-data"
METRICS_S3_PREFIX: str = "ctl/hcr/qc/_metrics"

# Known gene name corrections (typos in source data → canonical name).
_GENE_ALIASES: dict[str, str] = {
    "Slac17a7": "Slc17a7",
}

# Registry: sidebar display name → plot class
_PLOT_REGISTRY: dict[str, type] = {
    "Intensity Heatmap":          HeatmapPlot,
    "Normalized Counts Heatmap":  NormalizedCountsPlot,
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_all_metrics() -> pd.DataFrame:
    """List every ``*_metrics.json`` under METRICS_S3_PREFIX and return a tidy frame.

    Columns: ``mouse_id``, ``gene``, ``mean_intensity``, ``median_intensity``,
    ``std_intensity``, ``n_spots``.
    """
    _empty = pd.DataFrame(
        columns=["mouse_id", "gene", "mean_intensity",
                 "median_intensity", "std_intensity", "n_spots"]
    )
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    keys: list[str] = []
    for page in paginator.paginate(Bucket=METRICS_S3_BUCKET, Prefix=METRICS_S3_PREFIX + "/"):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("_metrics.json"):
                keys.append(obj["Key"])

    if not keys:
        return _empty

    rows: list[dict] = []
    for key in sorted(keys):
        try:
            resp = s3.get_object(Bucket=METRICS_S3_BUCKET, Key=key)
            data = json.loads(resp["Body"].read())
        except Exception:
            continue
        stem = key.split("/")[-1]  # e.g. "755252_metrics.json"
        mouse_id = data.get("mouse_id", stem.replace("_metrics.json", ""))
        for gene, vals in data.get("per_gene", {}).items():
            gene = _GENE_ALIASES.get(gene, gene)
            rows.append({"mouse_id": mouse_id, "gene": gene, **vals})

    if not rows:
        return _empty
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Tab class
# ---------------------------------------------------------------------------

class AllMiceTab(pn.viewable.Viewer):
    """All-mice tab: plot-type selector + inline controls + interactive plot."""

    def __init__(self, **params):
        super().__init__(**params)

        # -- plot-type dropdown (shown in the shared app sidebar) ----------
        self._plot_select = pn.widgets.Select(
            name="Plot",
            options=list(_PLOT_REGISTRY.keys()),
            value=list(_PLOT_REGISTRY.keys())[0],
            width=200,
        )

        # -- inline layout containers -------------------------------------
        self._controls_area = pn.Column(width=240, margin=(0, 0, 0, 0))
        self._plot_area = pn.Column(sizing_mode="stretch_width")

        # -- data and active plot -----------------------------------------
        self._df: pd.DataFrame = pd.DataFrame()
        self._active_plot = HeatmapPlot()

        # -- wire ---------------------------------------------------------
        self._plot_select.param.watch(self._on_plot_change, "value")

    # -- public API -------------------------------------------------------

    def reload(self) -> None:
        """Load metrics and rebuild the active plot."""
        self._df = _load_all_metrics()
        self._active_plot.load(self._df)
        self._controls_area.objects = [self._active_plot.controls()]
        self._plot_area.objects = [self._active_plot.plot_panel()]

    # -- callbacks --------------------------------------------------------

    def _on_plot_change(self, event) -> None:
        plot_cls = _PLOT_REGISTRY[event.new]
        self._active_plot = plot_cls()
        self._active_plot.load(self._df)
        self._controls_area.objects = [self._active_plot.controls()]
        self._plot_area.objects = [self._active_plot.plot_panel()]

    # -- layout for app.py integration ------------------------------------

    def sidebar_widgets(self) -> list:
        """Only the plot-type selector goes in the shared app sidebar."""
        return [self._plot_select]

    def main_area(self) -> pn.Column:
        """Controls column + plot sit side by side."""
        return pn.Column(
            pn.Row(
                self._controls_area,
                self._plot_area,
                sizing_mode="stretch_width",
            ),
            sizing_mode="stretch_width",
        )

    def __panel__(self):
        return pn.Row(
            pn.Column(*self.sidebar_widgets(), width=300),
            self.main_area(),
            sizing_mode="stretch_both",
        )
