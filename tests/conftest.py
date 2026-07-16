import builtins
import importlib
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path so that imports like `from models.xxx import yyy` work.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Create an isolated temporary directory with a minimal MWU-like structure.

    The directory is seeded with a ``resource/`` subdirectory and an otherwise
    empty layout suitable for testing interface loading, path resolution, etc.
    """
    project_dir = tmp_path / "mwu_project"
    project_dir.mkdir()
    (project_dir / "resource").mkdir()
    return project_dir


@pytest.fixture
def sample_interface() -> dict:
    """Return a minimal valid interface.json dict suitable for testing."""
    return {
        "interface_version": 2,
        "name": "TestGame",
        "label": "Test Game",
        "controller": [
            {
                "name": "AdbController",
                "type": "Adb",
            },
        ],
        "resource": [
            {
                "name": "main",
                "path": ["resource"],
            },
        ],
        "task": [
            {
                "name": "Startup",
                "entry": "Startup",
            },
        ],
        "option": {
            "difficulty": {
                "type": "select",
                "label": "Difficulty",
                "cases": [
                    {"name": "easy", "label": "Easy"},
                    {"name": "hard", "label": "Hard"},
                ],
                "default_case": "easy",
            },
        },
    }


@pytest.fixture
def main_module(monkeypatch, sample_interface: dict):
    """Import ``main`` without requiring user-provided integration files."""
    import fastapi.staticfiles
    import models.interface_loader
    from models.interface import InterfaceModel

    interface_model = InterfaceModel.model_validate(sample_interface)
    original_static_files = fastapi.staticfiles.StaticFiles

    class StaticFilesWithoutDirectoryCheck(original_static_files):
        def __init__(self, *args, **kwargs):
            kwargs["check_dir"] = False
            super().__init__(*args, **kwargs)

    def fail_on_input(*_args, **_kwargs):
        raise AssertionError("main import unexpectedly requested interactive input")

    monkeypatch.setattr(
        models.interface_loader, "load_interface_model", lambda _root: interface_model
    )
    monkeypatch.setattr(
        fastapi.staticfiles, "StaticFiles", StaticFilesWithoutDirectoryCheck
    )
    monkeypatch.setattr(builtins, "input", fail_on_input)

    sys.modules.pop("main", None)
    try:
        yield importlib.import_module("main")
    finally:
        sys.modules.pop("main", None)
