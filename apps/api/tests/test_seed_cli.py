"""Fresh-process seed bootstrap must register extension tables before creation."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from app.schema_registry import Base


def test_development_seed_cli_creates_all_feature_tables(tmp_path):
    # A fresh subprocess catches missing imports that full-app fixtures would mask.
    api_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "seed.db"
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "COMSPEC",
        "LOCALAPPDATA", "APPDATA", "USERPROFILE",
    }}
    env.update({"PYTHONPATH": str(api_root), "PYTHONIOENCODING": "utf-8",
                "ENVIRONMENT": "development", "DATABASE_URL": "sqlite:///" + database.as_posix(),
                "DEMO_MODE": "true", "AUTH_DEBUG_CODE": "true", "EMAIL_PROVIDER": "none",
                "STORAGE_PROVIDER": "none", "AUTH_SECRET": "isolated-seed-test-secret"})
    command = [sys.executable, "-X", "utf8", "-m", "app.seed",
               "--create-tables", "--reference-date", "2026-10-01"]
    first = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
    assert first.returncode == 0, "Isolated seed CLI failed"
    connection = sqlite3.connect(database)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(Base.metadata.tables) <= tables
        count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        connection.close()
    second = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    assert second.returncode == 0, "Repeated isolated seed CLI failed"
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == count
    finally:
        connection.close()
