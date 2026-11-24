"""Verify operator commands from the contents of a release bundle."""
from pathlib import Path
import runpy
import subprocess
import sys


def test_packaged_sources_can_plan_supabase_backup(tmp_path):
    root = Path(__file__).resolve().parents[3]
    packager = runpy.run_path(str(root / "deploy/package_release.py"))
    for name, data in packager["collect_sources"]().items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    assert (tmp_path / "apps/api/assets/certs/supabase-prod-ca-2021.crt").is_file()
    config = tmp_path / "source.env"
    config.write_text(
        "SUPABASE_DATABASE_URL=postgresql://test_role.testproject:synthetic@"
        "isolated.pooler.supabase.com:5432/postgres\n",
        encoding="utf-8",
    )
    plan = subprocess.run(
        [sys.executable, "-I", "deploy/postgres_backup.py", "backup", "--source-env-file", str(config)],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert "OFFLINE PLAN" in plan.stdout
