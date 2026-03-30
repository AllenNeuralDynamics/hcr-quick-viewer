# Viewer Performance: Strategies and Known Issues

This document tracks known performance concerns in `hcr-quick-viewer` and planned
strategies for addressing them as the plot catalog grows.

---

## Fixed

### DecompressionBombError on large images
**File:** `image_cache.py` — `_make_thumbnail()`  
**Status: Fixed**

PIL's default decompression-bomb limit is ~179 MP. Large pairplots and taxonomy
centroid grids can easily exceed this. The limit is now raised to 600 MP before
opening any image in `_make_thumbnail()`, which is well above any matplotlib
output while still protecting against genuine malicious inputs.

```python
Image.MAX_IMAGE_PIXELS = 600_000_000
```

---

## Known issues and planned strategies

### 1. Full image downloaded just to make a thumbnail

**Current flow:**
thumbnail request → `get_plot_bytes()` (full PNG, 10–50 MB) → decode + resize → cache

**Problems:**
- With `_MAX_ENTRIES=50` full images, peak RAM could reach 1–2 GB.
- `prefetch_thumbnails` fires 8 parallel S3 downloads on every mouse switch —
  a 30 MB × 8 burst (~240 MB) just to paint the grid.

**Planned:**
- Decouple the thumbnail path so fetching-for-thumbnail does NOT populate
  `_cache` (the full-image store). Thumbnails only need the full bytes transiently.
- Consider a byte-budget LRU (e.g. via `cachetools.LRUCache` with a custom
  `getsizeof`) instead of a count-based LRU, so large pairplots don't occupy
  the same slot as small violin plots.

---

### 2. Full raw bytes sent to browser for the viewer pane

**Current flow:**
card click → `get_plot_bytes()` → full PNG → Panel `PNG` pane → base64 over WebSocket

**Problems:**
- A 30 MB PNG becomes ~40 MB of base64 in the WebSocket payload.
- The on-screen pane is already `max_width=1200px`, so sending a 6000px-wide
  image wastes bandwidth and browser decode time.

**Planned:**
- Add a second image tier: `_VIEWER_WIDTH = 1600` (a middle resolution between
  200 px thumbnail and full-res).
- Route `_show_plot()` through `get_viewer_bytes(mouse_id, plot_type)` which
  produces and caches this intermediate size, instead of the raw download.
- Full-res download remains available via a dedicated download button.

---

### 3. Grid rebuild blocks the Panel callback thread

**Current flow:**
mouse select → `_rebuild_grid()` → `prefetch_thumbnails()` (synchronous, ~2–5 s) → `plot_grid.objects = cards`

**Problems:**
- The UI is frozen for the duration of the prefetch.
- On slow connections or with many plot types, this causes Panel to queue up
  other events.

**Planned:**
- Render the grid immediately with placeholder cards (grey boxes).
- Kick off thumbnail fetching in a background thread using `pn.state.execute()`
  or `asyncio` to push card updates incrementally as each thumbnail arrives.

---

### 4. Count-based LRU ignores image sizes

**Current:**
```python
_cache: LRUCache[str, bytes] = LRUCache(maxsize=50)
```

A pairplot PNG can be 50× larger than a violin plot PNG, but both occupy one
slot. As the plot catalog grows, peak memory is unpredictable.

**Planned:**
- Switch to a byte-budget LRU by passing `getsizeof=len` to `LRUCache`, with
  a total budget (e.g. 500 MB for full images, 50 MB for thumbnails).

```python
_cache: LRUCache[str, bytes] = LRUCache(
    maxsize=500 * 1024 * 1024, getsizeof=len
)
```

---

## File map

```
src/hcr_quick_viewer/viz_server/
    image_cache.py      # LRU caches, thumbnail generation ← main perf surface
    catalog.py          # TTL-cached S3 listing
    tabs/
        single_mouse.py # grid rebuild, prefetch_thumbnails call, _show_plot
        compare.py
```
