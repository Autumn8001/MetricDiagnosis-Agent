"""MetricSleuth backend package."""

import sys
from pathlib import Path


def _install_brotli_compat() -> bool:
    """Expose brotlicffi as brotli when no implementation is loaded yet."""
    try:
        import brotlicffi
    except ImportError:
        return False

    sys.modules.setdefault("brotli", brotlicffi)
    return sys.modules["brotli"] is brotlicffi


def _load_local_dotenv(start_path: Path | None = None) -> Path | None:
    """Load the nearest parent .env without replacing process environment."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    source_path = Path(__file__) if start_path is None else Path(start_path)
    for parent in source_path.resolve().parents:
        env_candidate = parent / ".env"
        if env_candidate.is_file():
            load_dotenv(dotenv_path=env_candidate, override=False)
            return env_candidate
    return None


_install_brotli_compat()
_load_local_dotenv()

__version__ = "0.1.0"
