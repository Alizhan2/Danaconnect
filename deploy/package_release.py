"""Package source and operator instructions from an explicit allowlist, offline."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent.parent
SOURCE_TYPES = {".py", ".ts", ".tsx", ".css", ".mjs", ".svg", ".ico"}
PUBLIC_TYPES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2"}
FORBIDDEN_PARTS = {"node_modules", ".next", "__pycache__", "tests", "private_uploads", "backups", ".git", ".vercel"}


def safe_file(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in FORBIDDEN_PARTS for part in relative.parts):
        return False
    if path.name.startswith(".env") and not (path.name == ".env.example" or path.name.endswith(".example")):
        return False
    if path.name.endswith((".enrollment.json", ".tsbuildinfo")):
        return False
    for ancestor in [path, *path.parents]:
        if ancestor == ROOT:
            break
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError("Release sources cannot contain links or junctions")
    path.resolve().relative_to(ROOT)
    return path.is_file()


def collect_sources() -> dict[str, bytes]:
    paths = set()
    for name in ["README.md", ".gitignore", ".dockerignore", ".vercelignore", "vercel.json", "compose.prod.yml"]:
        paths.add(ROOT / name)
    for service in ["api", "web", "admin"]:
        directory = ROOT / "apps" / service
        names = ["Dockerfile", ".env.example"]
        names += ["alembic.ini", "requirements.txt", "requirements.lock.txt", ".python-version"] if service == "api" else ["package.json", "package-lock.json", "tsconfig.json", "next-env.d.ts", "next.config.ts"]
        paths.update(directory / name for name in names)
        for source_dir in (["app", "migrations"] if service == "api" else ["src"]):
            paths.update(path for path in (directory / source_dir).rglob("*") if path.suffix in SOURCE_TYPES)
        if service != "api":
            paths.update(path for path in (directory / "public").rglob("*") if path.suffix.lower() in PUBLIC_TYPES)
    paths.update(path for path in (ROOT / "apps/api/assets/fonts").glob("*") if path.suffix.lower() in {".ttf", ".txt", ".md"})
    paths.update(path for path in (ROOT / "scripts").rglob("*") if path.suffix in {".py", ".ps1", ".sh", ".mjs"})
    paths.update(ROOT / "deploy" / name for name in ["generate_config.py", "readiness.py", "package_release.py", "vercel_config.py", "migrate_external.py", "configure_qstash.py", "compose.worker.yml", "Caddyfile", "s3-policy.example.json", "vercel.cron.example.json", ".env.production.example", ".env.worker.example", ".env.vercel.example"])
    paths.update(ROOT / "docs" / name for name in ["CLOUD_RUNBOOK.md", "RELEASE_PREPARATION.md", "IMPLEMENTATION_STATUS.md", "PILOT_RELEASE_PLAN.md", "MONITORING_RUNBOOK.md", "BLOB_STORAGE.md", "ACTIVATION_STATUS.md", "OWNER_ACTIVATION.md", "QSTASH_RUNBOOK.md", "GIT_DEPLOYMENT.md"])
    contents = {}
    for path in sorted(paths):
        if not safe_file(path):
            continue
        data = path.read_bytes()
        if len(data) > 12 * 1024 * 1024:
            raise ValueError("A release source exceeds the size limit")
        contents[path.relative_to(ROOT).as_posix()] = data
    if sum(map(len, contents.values())) > 64 * 1024 * 1024:
        raise ValueError("Release source size exceeds the limit")
    required = ["vercel.json", "apps/api/app/main.py", "apps/api/assets/fonts/DejaVuSans.ttf", "apps/api/assets/fonts/LICENSE-DejaVu.txt", "apps/web/package-lock.json", "apps/admin/package-lock.json"]
    if any(name not in contents for name in required):
        raise ValueError("Required release sources are missing")
    return contents


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            self.print_usage()
            self.exit(2, "Invalid arguments; use --output with a new ZIP path inside artifacts.\n")

    parser = SafeParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New ZIP path inside the workspace artifacts folder")
    args = parser.parse_args()
    try:
        target = args.output.resolve()
        target.relative_to(ROOT / "artifacts")
        if target.suffix.lower() != ".zip":
            raise ValueError("Release output must be a ZIP")
        for ancestor in [args.output.absolute(), *args.output.absolute().parents]:
            if ancestor == ROOT:
                break
            if ancestor.is_symlink() or ancestor.is_junction():
                raise ValueError("Release output cannot use links or junctions")
        contents = collect_sources()
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
        fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        manifest = {"format": 1, "kind": "source-release", "created_at": datetime.now(timezone.utc).isoformat(),
            "source_fingerprint": fingerprint, "files": hashes,
            "scope": "Source, lockfiles, licensed font, templates and instructions. No installed dependencies, builds, databases or private environment files.",
            "deployment_status": "not-verified-by-packager", "verification": "Packaging does not confirm functional flows, provider connections or cloud deployment. Read ACTIVATION_STATUS.md for separate operator evidence."}
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in contents.items():
                    archive.writestr(name, data)
                archive.writestr("RELEASE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(f"Source release created: {len(contents)} files")
        print(f"Source fingerprint: {fingerprint}")
    except (OSError, ValueError, zipfile.BadZipFile):
        # Never expose local private paths or file contents through tracebacks.
        print("Source release could not be packaged. Check output availability and required source files.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
