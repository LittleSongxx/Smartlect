"""Verify the frozen handoff inputs; optionally extract them inside this project.

python handoff/verify_package.py
python handoff/verify_package.py --extract
Extraction is for reference only. Implement Smartlect outside handoff/.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def within(root, relative):
    path = PurePosixPath(relative.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in str(path):
        raise ValueError(f"Unsafe path: {relative}")
    result = (root / Path(*path.parts)).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes target: {relative}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "handoff/manifest.json").read_text(encoding="utf-8"))
    sources = list(manifest["sources"])
    integration = ROOT / "handoff/integration-manifest.json"
    if integration.exists():
        sources.extend(json.loads(integration.read_text(encoding="utf-8"))["sources"])
    records = sources + manifest["context_files"]
    for record in records:
        path = within(ROOT, record.get("archive", record.get("path")))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"Checksum mismatch: {path.relative_to(ROOT)}")

    for source in sources:
        target = within(ROOT, "handoff/extracted/" + source["id"])
        with zipfile.ZipFile(within(ROOT, source["archive"])) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"Corrupt archive: {source['archive']}")
            files = [entry for entry in archive.infolist() if not entry.is_dir()]
            if len(files) != source["files"] or len({f.filename for f in files}) != len(files):
                raise ValueError(f"File count mismatch: {source['id']}")
            members = {m["path"]: m for m in source.get("members", [])}
            if members and set(members) != {f.filename for f in files}:
                raise ValueError(f"Member whitelist mismatch: {source['id']}")
            for entry in files:
                destination = within(target, entry.filename)
                parts = PurePosixPath(entry.filename).parts
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError(f"Symlink in archive: {entry.filename}")
                excluded = {".git", "target", ".venv", "node_modules", "__pycache__"}
                if not members:
                    excluded.update({"AI_Shop-agent", "AI_Shop-front"})
                if any(part in excluded or (members and part.startswith(".env")) for part in parts):
                    raise ValueError(f"Excluded content: {entry.filename}")
                allowed = source.get("included_roots", members)
                if not any(entry.filename == item or (not members and entry.filename.startswith(item + "/")) for item in allowed):
                    raise ValueError(f"Unexpected archive member: {entry.filename}")
                content = archive.read(entry)
                if members:
                    member = members[entry.filename]
                    blob = f"blob {len(content)}\0".encode() + content
                    if (hashlib.sha256(content).hexdigest() != member["sha256"]
                            or hashlib.sha1(blob).hexdigest() != member["git_blob"]):
                        raise ValueError(f"Frozen member checksum mismatch: {entry.filename}")
                if args.extract:
                    if destination.exists():
                        if destination.read_bytes() != content:
                            raise ValueError(f"Refusing to overwrite modified reference: {destination}")
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(content)
        print(f"Verified {source['id']}: {source['files']} files")
    print(f"Verified {len(records)} checksums. Source projects are not accessed.")
    if args.extract:
        print("Reference sources extracted into handoff/extracted/; do not run their legacy startup scripts.")


if __name__ == "__main__":
    main()
