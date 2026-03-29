# hcr-quick-viewer

[![License](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)

A Panel-based QC viewer for browsing HCR plots stored on S3.

## Getting Started

### Install

```bash
pip install -e .
```

### Launch

The app is served via [Panel](https://panel.holoviz.org/). From the repo root:

```bash
panel serve src/hcr_quick_viewer/viz_server/app.py \
    --address 0.0.0.0 --port 5006 \
    --allow-websocket-origin "*" \
    --num-threads 4
```


For development, add `--autoreload` to auto-restart on code changes.

Then open http://localhost:5006 in your browser.

### AWS credentials

The viewer reads QC plots from S3 (`aind-scratch-data`). Make sure your AWS credentials are configured (e.g. `~/.aws/credentials` or environment variables).

## Development

```bash
uv run pytest tests
uv run ruff check
```
