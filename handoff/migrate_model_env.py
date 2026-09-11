"""Copy only explicitly authorized provider settings, without executing dotenv content.

Run with the Smartlect venv. The source argument must name the old model .env.
Output is a literal key=value file for the Python launcher, never a shell script.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {
    "LLM_API_KEY": "MODEL_API_KEY", "LLM_BASE_URL": "MODEL_BASE_URL",
    "EMBEDDING_API_KEY": "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL": "EMBEDDING_BASE_URL",
    "EMBEDDING_MODEL": "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS": "EMBEDDING_DIMENSIONS",
    "EMBEDDING_PROVIDER": "EMBEDDING_PROVIDER", "RERANK_API_KEY": "RERANK_API_KEY",
    "RERANK_BASE_URL": "RERANK_BASE_URL", "RERANK_MODEL": "RERANK_MODEL",
    "RERANK_API_FORMAT": "RERANK_API_FORMAT",
}


def select_model_fields(values):
    selected = {"SMARTLECT_" + target: values[source].strip() for source, target in FIELDS.items()
                if values.get(source) and values[source].strip()}
    if "SMARTLECT_RERANK_API_KEY" not in selected and values.get("DASHSCOPE_API_KEY"):
        selected["SMARTLECT_RERANK_API_KEY"] = values["DASHSCOPE_API_KEY"].strip()
    if "SMARTLECT_EMBEDDING_PROVIDER" not in selected and values.get("SPRING_AI_MODEL_EMBEDDING"):
        selected["SMARTLECT_EMBEDDING_PROVIDER"] = values["SPRING_AI_MODEL_EMBEDDING"].strip()
    selected["SMARTLECT_MODEL_ID"] = "qwen3.7-plus"
    for key, value in selected.items():
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value) or "${" in value:
            raise ValueError(f"Invalid literal or unresolved interpolation in {key}")
        if key.endswith("_BASE_URL"):
            url = urlsplit(value)
            # This export is for the inspected Alibaba provider, not arbitrary old application URLs.
            if (url.scheme != "https" or url.username or url.password or url.query or url.fragment
                    or url.port not in (None, 443) or not re.fullmatch(
                        r"(?:dashscope(?:-intl|-us)?\.aliyuncs\.com|llm-[a-z0-9-]+\.[a-z0-9-]+\.maas\.aliyuncs\.com)",
                        url.hostname or "")):
                raise ValueError(f"{key} is not the verified model provider endpoint")
    for prefix in ("MODEL", "EMBEDDING", "RERANK"):
        if selected.get(f"SMARTLECT_{prefix}_API_KEY") and not selected.get(f"SMARTLECT_{prefix}_BASE_URL"):
            raise ValueError(f"SMARTLECT_{prefix}_BASE_URL missing for configured provider key")
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    destination = ROOT / "run/model.env"
    if args.source.is_symlink() or not args.source.is_file():
        raise SystemExit("Source must be a regular model dotenv file")
    if subprocess.run(["git", "check-ignore", "-q", str(destination)], cwd=ROOT).returncode:
        raise SystemExit("Destination is not Git-ignored")
    if subprocess.check_output(["git", "ls-files", "--", str(destination)], cwd=ROOT).strip():
        raise SystemExit("Destination is tracked; refusing to copy credentials")
    selected = select_model_fields(dotenv_values(args.source, interpolate=False))
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write("# Literal provider fields only. Read by Python; do not source in a shell.\n")
        output.write("\n".join(f"{key}={value}" for key, value in sorted(selected.items())) + "\n")
    print(json.dumps({"destination": "run/model.env", "mode": "0600", "fields": sorted(selected),
                      "chat_configured": bool(selected.get("SMARTLECT_MODEL_API_KEY")),
                      "model": "qwen3.7-plus", "live_called": False}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        raise SystemExit("Model configuration export failed; verify field presence, provider URL, and destination permissions. Values suppressed.")
