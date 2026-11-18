import sys


def configure_utf8_stdout() -> None:
    """Preserve Arabic and mixed-language JSON on Windows consoles."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="strict")
