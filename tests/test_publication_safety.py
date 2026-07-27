import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "MCP_Server" / "server.py"
REMOTE = ROOT / "AbletonMCP_Remote_Script" / "__init__.py"


def assignment_value(path, name):
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} was not found")


def test_remote_script_is_loopback_only():
    assert assignment_value(REMOTE, "HOST") == "127.0.0.1"
    assert "127.0.0.1" in SERVER.read_text()


def test_no_telemetry_or_supabase_runtime():
    public_runtime = "\n".join(
        path.read_text()
        for path in [SERVER, ROOT / "pyproject.toml"]
    ).lower()
    assert "telemetry" not in public_runtime
    assert "supabase" not in public_runtime
    assert not (ROOT / "MCP_Server" / "telemetry.py").exists()
    assert not (ROOT / "MCP_Server" / "telemetry_decorator.py").exists()


def test_no_machine_specific_publication_artifacts():
    forbidden_names = {"REAL_SERVER_PATH.txt", ".DS_Store", "customer_uuid.txt"}
    ignored_parts = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "build",
        "dist",
    }
    files = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & ignored_parts)
    ]
    assert not ({path.name for path in files} & forbidden_names)
    assert not any(path.suffix == ".pyc" for path in files)

    text = "\n".join(
        path.read_text(errors="ignore")
        for path in files
        if path.suffix in {".py", ".toml", ".md", ".yaml", ".yml", ".json", ".txt"}
    )
    assert not re.search(r"/Users/[A-Za-z0-9._-]+/", text)
    assert not re.search(r"/home/[A-Za-z0-9._-]+/", text)
