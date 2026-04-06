# Changelog

All notable changes to `hcr-quick-viewer` are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.2.0] – 2026-04-06

### Added

#### Round-specific QC tab
- New **Round Plots** inner tab on the Single Mouse view displays one card per imaging round.
- Each card shows:
  - Acquisition date + time as the card title (e.g. `R2: 2025-07-10  13:00`)
  - Thumbnail of the `tile_overview_ch405` Z-max projection plot
  - Gene table footer: **Round N** (bold) followed by `channel – gene` rows for up to 6 channels, sourced from the processing manifest sidecar
- Cards are fixed height (430 px) for a uniform grid regardless of gene count.
- Clicking a card opens a **round detail view** showing:
  - Back button to return to the card grid
  - Asset name, raw asset name, and channel→gene table
  - Thumbnail grid of all round-level plots for that asset
  - Full-size image viewer + metadata strip when a thumbnail is clicked

#### Round-level S3 catalog & image cache
- `catalog.load_round_catalog(mouse_id)` — lists per-asset sub-folders under `ctl/hcr/qc/{mouse_id}/` and returns `{asset_name: [plot_types]}`.
- `catalog.load_round_plot_metadata(mouse_id, asset_name, plot_type)` — fetches the JSON sidecar for a round-level plot.
- `image_cache.get_round_plot_bytes / get_round_thumbnail_bytes / prefetch_round_thumbnails` — dedicated fetch and LRU-cache functions for round plots, keyed separately from integrated (mouse-level) plots.
- Fixed integrated plot discovery: inner S3 paginator now uses `Delimiter="/"` so round sub-folder objects no longer bleed into the integrated plot catalog.

#### Round QC pipeline (`run_capsule.py`)
- `run_round_qc()` iterates over each round in the catalog record, generates a `tile_overview_ch405` Z-max projection via `plot_tile_overview()`, and uploads it to:
  ```
  ctl/hcr/qc/{mouse_id}/{processed_asset_name}/tile_overview_ch405.png
  ```
- JSON sidecar includes `round_label`, `source_assets` (processed + raw asset names), `plot_kwargs`, and `gene_dict` from the processing manifest.
- Raw asset name is derived automatically by stripping the `_processed_<date>_<time>` suffix.

#### `sample_overview.py` refactor (`aind-hcr-qc`)
- Replaced prototype with two clean functions:
  - `raw_asset_name_from_processed(processed_name)` — regex strip of `_processed_*` suffix.
  - `plot_tile_overview(hcr_round, channel, pyramid_level, vmax)` — loads fused zarr via `HCRRound.load_zarr_channel()`, squeezes OME-Zarr singleton dims, computes a lazy dask Z-max projection, returns a `matplotlib.Figure`.
- No custom S3 or zarr access code; delegates entirely to the `aind_hcr_data_loader` API.

#### `s3_qc.py` additions (`aind-hcr-qc`)
- `_get_round_s3_key()` — canonical key builder for round-level artifacts.
- `check_round_plot_exists()` — HEAD-only existence check.
- `upload_round_plot()` — uploads PNG + JSON sidecar to the asset-scoped S3 sub-path.

### Fixed

- **zarr v3 `TypeError`** (`path=3 is not a string`): `HCRRound.load_zarr_channel()` now passes `str(pyramid_level)` to the zarr group subscript, as zarr v3 requires string keys.
- **FUSE-mount `stat()` hang** in `get_processing_manifests()`: replaced two sequential `Path.exists()` calls (which block on non-existent FUSE paths) with a single `Path.iterdir()` scan of the round folder top-level, avoiding the network round-trip through a missing `derived/` directory.

---

## [0.1.0] – initial release

- Single Mouse tab with integrated QC plot thumbnails, full-size viewer, metadata strip, and neuroglancer links.
- Compare Mice tab for side-by-side plot comparison across mice.
- All Mice tab with intensity heatmap and normalized counts heatmap.
- TTL-cached S3 catalog with LRU image/thumbnail caches.
- Arrow-key navigation between plots.
- Category filter for plot types.
