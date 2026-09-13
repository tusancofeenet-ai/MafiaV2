import ast
import importlib
from pathlib import Path


def test_clean_entrypoint_has_no_legacy_runtime_imports():
    source = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert "main1" not in imported_modules
    assert "player_runtime_entry" not in imported_modules
    assert "main_final" not in imported_modules
    assert "main_refactored_v4" in imported_modules
    assert "runtime.final_persistence" in imported_modules


def test_clean_entrypoint_imports_without_network_startup(monkeypatch, tmp_path):
    """Importing main.py must construct the clean app without starting polling."""
    monkeypatch.setenv("API_TOKEN", "123456:TEST_TOKEN")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'bootstrap.sqlite3'}")

    import sys
    sys.modules.pop("main", None)
    module = importlib.import_module("main")

    assert module.app is not None
    assert module.bot is module.app.bot
    assert module.dp is module.app.dp
    assert module.persistence_status["fsm"] is False
    assert module.persistence_status["scenarios"] is True
    assert module.persistence_status["addons"] is True
    assert module.app.dp.loop is None or not module.app.dp.loop.is_running()
