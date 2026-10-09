"""Read-only helpers for locating versioned application-state migrations."""

from __future__ import annotations

from pathlib import Path

from app.persistence.models import PersistenceError


MIGRATIONS_DIRECTORY = Path(__file__).resolve().parents[2] / "migrations"
DEFAULT_MIGRATION_NAME = "001_app_state.sql"


def _safe_migration_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise PersistenceError("Migration name must be a non-empty string.")
    clean_name = name.strip()
    if Path(clean_name).name != clean_name or not clean_name.endswith(".sql"):
        raise PersistenceError("Migration name must be a plain .sql filename.")
    return clean_name


def available_migrations() -> tuple[str, ...]:
    """List migration filenames without opening a database or executing SQL."""

    if not MIGRATIONS_DIRECTORY.is_dir():
        return ()
    return tuple(
        sorted(
            path.name
            for path in MIGRATIONS_DIRECTORY.iterdir()
            if path.is_file() and path.suffix == ".sql"
        )
    )


def load_migration(name: str = DEFAULT_MIGRATION_NAME) -> str:
    """Read one migration's SQL text.

    This function intentionally has no execution path.  Applying migrations is
    a later deployment concern and must use an explicitly configured database.
    """

    clean_name = _safe_migration_name(name)
    path = MIGRATIONS_DIRECTORY / clean_name
    if not path.is_file():
        raise FileNotFoundError(f"Migration does not exist: {clean_name}")
    return path.read_text(encoding="utf-8")


def load_app_state_migration() -> str:
    """Read the R2-001 application-state migration."""

    return load_migration(DEFAULT_MIGRATION_NAME)


__all__ = [
    "DEFAULT_MIGRATION_NAME",
    "MIGRATIONS_DIRECTORY",
    "available_migrations",
    "load_app_state_migration",
    "load_migration",
]
