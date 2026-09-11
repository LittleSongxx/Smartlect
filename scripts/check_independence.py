"""Fail on legacy runtime names, source-workspace dependencies, or escaping links."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROOTS = ("backend", "growth", "web", "deploy", "scripts", "fixtures")
SKIP_DIRS = {"target", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "dist", "licenses"}
SKIP_FILES = {"check_independence.py", "migrate_java.py", "LICENSE", "LICENSE.md", "NOTICE", "SOURCES.md"}
PATTERNS = {
    "legacy brand": re.compile(r"ai_shop|aishop|smarlect|simlect|multi-agent-ad-optimizer|multi-agent-ecommerce-system", re.I),
    "legacy config/cache": re.compile(r"\bECOM_|\bmall:"),
    "legacy attribution": re.compile(r"\bai(RequestId|Position|Source|AttributedAt)\b|\bai_(request_id|position|source|attributed_at)\b"),
    "removed Java search/schema": re.compile(r"\bsmartlect[-_]search\b|\b(?:agent_message|agent_learning|rag_question|faq_candidate|knowledge_base)\b"),
    "reference runtime dependency": re.compile(r"handoff[/\\]extracted|/home/song/code/(Java|Agent)/|\\\\wsl[^\n]*(AI_Shop|multi-agent)"),
}


def scan(root):
    problems = []
    count = 0
    for base in ROOTS:
        directory = root / base
        if directory.is_symlink() and not directory.resolve().is_relative_to(root.resolve()):
            problems.append(f"{base}: link escapes project")
            continue
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            relative = path.relative_to(root)
            if any(part in SKIP_DIRS or part.startswith(".venv-") or part.endswith(".egg-info") for part in relative.parts):
                continue
            if path.is_symlink() and not path.resolve().is_relative_to(root.resolve()):
                problems.append(f"{relative}: link escapes project")
            if not path.is_file() or path.name in SKIP_FILES:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            count += 1
            for label, pattern in PATTERNS.items():
                if pattern.search(str(relative)):
                    problems.append(f"{relative}: {label} in path")
                for number, line in enumerate(content.splitlines(), 1):
                    if pattern.search(line):
                        problems.append(f"{relative}:{number}: {label}")
    return count, problems


def repository_problems(root):
    problems = []
    if (root / ".git").is_symlink() or not (root / ".git").is_dir():
        problems.append(".git: expected independent repository directory, not a symlink")
    if (root / ".gitmodules").exists():
        problems.append(".gitmodules: submodules are not independent inputs")
    return problems


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "backend").mkdir()
        sample = root / "backend/application.yml"
        sample.write_text("name: aishop-product\npath: handoff/extracted/code\n")
        count, problems = scan(root)
        assert count == 1 and len(problems) == 2
        sample.write_text("name: smartlect-product\n")
        assert scan(root) == (1, [])
        sample.write_text("INSERT INTO smartlect_search.rag_question VALUES (1);\n")
        assert len(scan(root)[1]) == 1
        sample.write_text("User-Agent header and JaCoCo prepare-agent are valid.\n")
        assert scan(root) == (1, [])
        (root / "web").mkdir()
        page = root / "web/App.vue"
        page.write_text("<div>Smartlect Shopping Agent / KnowledgeBase</div>\n")
        assert scan(root) == (2, [])
        page.write_text("<div>AI_Shop</div>\n")
        assert len(scan(root)[1]) == 1
        page.unlink()
        with tempfile.TemporaryDirectory() as external:
            (root / "growth").symlink_to(external, target_is_directory=True)
            assert scan(root)[1] == ["growth: link escapes project"]
            (root / ".git").symlink_to(external, target_is_directory=True)
            assert repository_problems(root)
    print("Independence scanner self-test passed.")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    count, problems = scan(ROOT)
    problems.extend(repository_problems(ROOT))
    for name in ("run/runtime.env", "run/model.env"):
        path = ROOT / name
        if path.exists():
            ignored = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0
            tracked = subprocess.check_output(["git", "ls-files", "--", name], cwd=ROOT).strip()
            if not ignored or tracked:
                problems.append(f"{name}: credentials are not untracked and Git-ignored")
            if path.is_symlink() or path.stat().st_mode & 0o777 != 0o600:
                problems.append(f"{name}: credentials must be a regular file with mode 600")
    print(f"Scanned {count} runtime files; {len(problems)} independence/naming violation(s).")
    print("Excluded: licenses/source records, build/venv output, migration-only tool and scanner definitions.")
    for problem in problems:
        print(problem)
    sys.exit(bool(problems))
