"""Explicit local data home; never discovers or copies another application's data."""
import os
import stat
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent


def reject_links(path):
    """Reject existing linked components without reading file contents."""
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Linked runtime path rejected")
        try:
            attrs = getattr(part.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            continue
        # Python 3.10/3.11 have no Path.is_junction; reparse attributes cover them.
        if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("Linked runtime path rejected")
    return path


def resolve_home(value=None):
    if value is None:
        value = os.environ.get("COMPANION_HOME")
    if value is None:
        return reject_links(APP_ROOT)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("COMPANION_HOME must be an existing absolute directory")
    path = Path(value)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("COMPANION_HOME must be an existing absolute directory")
    reject_links(path)
    return path.resolve(strict=True)


DATA_ROOT = resolve_home()


def data_path(*parts):
    path = DATA_ROOT.joinpath(*parts)
    reject_links(path)
    if not path.resolve().is_relative_to(DATA_ROOT.resolve()):
        raise ValueError("Runtime path outside configured home")
    return path


def anchor_path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Anchor path required")
    path = Path(value)
    if not path.is_absolute():
        path = data_path(value)
    reject_links(path)
    return path
