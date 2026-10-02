"""Run API tests in a disposable directory without deployment credentials."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    # Keep only OS/runtime paths. Settings never inherit production providers,
    # database URLs, authentication keys or dotenv files from the workspace.
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP",
               "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HOME"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    with tempfile.TemporaryDirectory(prefix="danaconnect-api-tests-") as directory:
        env.update({
            "PYTHONPATH": str(root / "apps/api"), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
            "ENVIRONMENT": "test", "AUTH_DEBUG_CODE": "true", "DEMO_MODE": "false",
            "DATABASE_URL": "sqlite:///" + (Path(directory) / "runtime.db").as_posix(),
            "AUTH_SECRET": "isolated-test-secret-never-used-for-deployment",
            "EMAIL_PROVIDER": "none", "STORAGE_PROVIDER": "none", "AI_ENABLED": "false",
        })
        return subprocess.call([sys.executable, "-X", "utf8", "-m", "pytest",
                                str(root / "apps/api/tests"), *(sys.argv[1:] or ["-q"])],
                               cwd=directory, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
