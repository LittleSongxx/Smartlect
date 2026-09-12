#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
runtime_python="${SMARTLECT_RUNTIME_PYTHON:-/usr/bin/python3}"
command="${1:-help}"
if [[ $# -gt 0 ]]; then shift; fi
case "$command" in
  bootstrap|config|model-mode|status|infra-up|infra-check|up|apps-check|apps-down|down|catalog)
    exec "$runtime_python" scripts/runtime.py "$command" "$@" ;;
  build)
    "$runtime_python" scripts/check_independence.py
    mvn -B -f backend/pom.xml package "$@"
    if [[ ! -x growth/.venv/bin/python ]]; then
      python_bin=''
      for candidate in "${SMARTLECT_PYTHON:-}" python3.13 python3.12 python3.11 "$HOME/miniconda3/bin/python" python3; do
        if [[ -n "$candidate" ]] && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
          python_bin="$candidate"
          break
        fi
      done
      [[ -n "$python_bin" ]] || { echo 'Python >=3.11 required; set SMARTLECT_PYTHON.' >&2; exit 1; }
      "$python_bin" -m venv growth/.venv
    fi
    growth/.venv/bin/python -m pip install -r growth/requirements.lock
    growth/.venv/bin/python -m pip install --no-index --no-deps --no-build-isolation ./growth
    growth/.venv/bin/python -m pip check
    growth/.venv/bin/python -c 'import smartlect; print("Smartlect Growth import OK")'
    npm --prefix web/user ci --ignore-scripts
    npm --prefix web/user run build
    npm --prefix web/admin ci --ignore-scripts
    npm --prefix web/admin run build ;;
  check)
    "$runtime_python" scripts/check_independence.py
    "$runtime_python" scripts/runtime.py self-test
    mvn -B -f backend/pom.xml test "$@"
    growth/.venv/bin/python -m unittest discover -s growth/tests
    npm --prefix web/user run test
    npm --prefix web/admin run test ;;
  demo)
    "$runtime_python" scripts/runtime.py apps-check
    exec growth/.venv/bin/python scripts/demo.py "$@" ;;
  seed-store)
    "$runtime_python" scripts/runtime.py apps-check
    exec growth/.venv/bin/python scripts/seed_store_playbook.py "$@" ;;
  reset-demo)
    exec growth/.venv/bin/python scripts/reset_demo.py "$@" ;;
  help)
    echo 'Usage: ./scripts/dev.sh {bootstrap|config|model-mode|build|check|infra-up|infra-check|up|apps-check|status|apps-down|down|catalog|demo|seed-store|reset-demo}' ;;
  *) echo "Unknown command: $command" >&2; exit 2 ;;
esac
