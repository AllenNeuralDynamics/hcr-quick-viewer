"""Smoke test — importability."""


def test_package_importable() -> None:
    import hcr_quick_viewer
    assert hasattr(hcr_quick_viewer, "__version__")