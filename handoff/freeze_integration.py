"""One-time, read-only Git object export for Final Integration F0. Never runs sources."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
AI = "AI_Shop-backend/AI_Shop-agent/"
FRONT = "AI_Shop-front/"
KNOWLEDGE = "AI_Shop-backend/data/demo_knowledge/"
MANIFEST = ROOT / "handoff/integration-manifest.json"


def group_for(path):
    if path == "LICENSE.md":
        return "license"
    if path.startswith(AI):
        name = path[len(AI):]
        if name in {"pyproject.toml", "requirements.lock", "uv.lock"}:
            return "shop-ai-python"
        if name.startswith(("app/", "tests/", "evaluation/", "fault_drill/")) and name.endswith(".py"):
            return "shop-ai-python"
        if name.startswith("prompts/") and name.endswith(".txt"):
            return "shop-ai-python"
        if name in {"app/config/search_runtime_taxonomy.yml", "app/config/search_taxonomy.yml",
                    "app/resources/analytics-catalog-v0.provisional.json"}:
            return "shop-ai-python"
    if path.startswith(KNOWLEDGE) and path.endswith(".md"):
        return "shop-ai-python"
    if path.startswith(FRONT):
        parts = path[len(FRONT):].split("/")
        if parts[0] not in {"AI_Shop-web", "AI_Shop-admin"}:
            return None
        name = "/".join(parts[1:])
        suffix = PurePosixPath(name).suffix
        if name.startswith(("src/", "tests/")) and suffix in {
                ".vue", ".ts", ".js", ".mjs", ".json", ".css", ".scss", ".svg"}:
            return "shop-frontends"
        if len(parts) == 2 and name in {
                "README.md", "package.json", "package-lock.json", "index.html", "eslint.config.mjs",
                "jsconfig.json", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json",
                "postcss.config.cjs", "vite.config.js", "vite.config.ts",
                "vitest.config.js", "vitest.config.ts", "playwright.config.ts"}:
            return "shop-frontends"
        if name == "scripts/check-bundle-budget.mjs":
            return "shop-frontends"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--commit", required=True, help="Full SHA resolved once at handover")
    args = parser.parse_args()
    if MANIFEST.exists():
        raise SystemExit("Already frozen; use verify_package.py. Refusing to replace the input manifest.")

    def git(*command):
        return subprocess.check_output(["git", "-C", str(args.source), *command])

    before = git("rev-parse", "HEAD").decode().strip()
    if before != args.commit or len(args.commit) != 40:
        raise SystemExit("Source HEAD differs from the pinned full SHA; no export performed.")
    groups = {"shop-ai-python": [], "shop-frontends": []}
    excluded = Counter()
    for entry in git("ls-tree", "-rz", args.commit).split(b"\0"):
        if not entry:
            continue
        meta, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        path = raw_path.decode()
        group = group_for(path)
        if group:
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError(f"Non-regular source: {path}")
            data = git("cat-file", "blob", oid)
            record = (path, data, oid)
            for target in (groups if group == "license" else [group]):
                groups[target].append(record)
        elif path.startswith((AI, FRONT, KNOWLEDGE)):
            excluded["/".join(path.split("/")[:3])] += 1
    if git("rev-parse", "HEAD").decode().strip() != before:
        raise SystemExit("Source HEAD moved during export; no archives written.")

    sources = []
    for name, files in groups.items():
        if len(files) < 10 or not any(p == "LICENSE.md" for p, _, _ in files):
            raise ValueError(f"Expected source modules/license missing: {name}")
        archive_path = ROOT / "handoff/sources" / f"{name}.zip"
        with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data, _ in sorted(files):
                info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        sources.append({
            "id": name, "archive": str(archive_path.relative_to(ROOT)),
            "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(), "files": len(files),
            "license": {"path": "LICENSE.md", "spdx": "MIT", "copyright": "2026 Audreator"},
            "members": [{"path": p, "git_blob": oid, "sha256": hashlib.sha256(data).hexdigest()}
                        for p, data, oid in sorted(files)],
        })
    manifest = {
        "schema_version": 1, "frozen_at": datetime.now(timezone.utc).isoformat(),
        "source_repository": str(args.source.resolve()), "commit": before,
        "head_before": before, "head_after": before, "source_access": "Git objects only; no working-tree files",
        "sources": sources, "selection_policy": "handoff/freeze_integration.py:group_for",
        "exclusions": ["uncommitted/untracked files", ".env including examples", "Git/build/venv/node_modules",
                       "startup/deploy scripts", "runtime results/logs/evaluation-evidence", "datasets/fixtures with unverified provenance",
                       "knowledge catalog/index metadata and later knowledge versions", "uploads/business data/credentials/model weights",
                       "legacy public reference site/PWA assets", "binary frontend media with unverified provenance"],
        "excluded_tracked_counts": dict(sorted(excluded.items())),
        "use": "Reference input only; adapt into Smartlect, never import or run directly",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"commit": before, "archives": [{"id": s["id"], "files": s["files"], "sha256": s["sha256"]}
                                                   for s in sources]}, indent=2))


if __name__ == "__main__":
    main()
