"""Load service-owned SQL without allowing paths to escape their directory."""

from pathlib import Path


def load_query(directory: Path, name: str) -> str:
    """Return a UTF-8 SQL file contained directly beneath ``directory``."""
    if Path(name).suffix != ".sql":
        raise ValueError("SQL query names must use the .sql suffix")

    query_directory = directory.resolve(strict=True)
    query_path = (query_directory / name).resolve(strict=True)
    if query_path.parent != query_directory:
        raise ValueError("SQL query must be contained in the service SQL directory")

    return query_path.read_text(encoding="utf-8")
