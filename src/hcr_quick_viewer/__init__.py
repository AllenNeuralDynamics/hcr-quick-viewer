from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("hcr-quick-viewer")
except PackageNotFoundError:
    __version__ = "dev"
