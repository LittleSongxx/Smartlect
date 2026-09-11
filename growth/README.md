# Smartlect Growth

The installable `smartlect` package provides a FastAPI entry, trusted Java cookie
sessions, confirmed transaction proposals and durable recovery, plus deterministic
experiment assignment and advertising calculations. A separate `smartlect.worker`
process consumes commerce facts into the MySQL ledger described in `LEDGER.md`.
Shopping now runs bounded LangGraph ReAct with versioned skills, source citations,
owned memory and human handoff. Recommendations and immutable attribution are implemented; campaign/Merchant
execution remain F4–F5 work. No model tool can approve a transaction.

```bash
python3.11 -m venv growth/.venv
growth/.venv/bin/python -m pip install -r growth/requirements.lock
growth/.venv/bin/python -m pip install --no-deps --no-build-isolation ./growth
growth/.venv/bin/python -m pip check
growth/.venv/bin/python -m unittest discover -s growth/tests -v
growth/.venv/bin/python -m smartlect.app --check
growth/.venv/bin/python -m smartlect.app
```

Any Python >=3.11 may replace `python3.11`; the current WSL verification uses
`/home/song/miniconda3/bin/python` (3.13.11) to create the clean virtual environment.
Run from the Smartlect root. `GET /health` listens on `127.0.0.1:18000` by default.
`SMARTLECT_GROWTH_HOST` and `SMARTLECT_GROWTH_PORT` change the bind address.
`SMARTLECT_MODEL_MODE` accepts `mock`, `rule-fallback`, or `live`.
Use `./scripts/dev.sh model-mode live` then `up` after configuring the provider.

Direct dependencies are declared in `pyproject.toml`; the single
`requirements.lock` pins their full closure, including MySQL RSA authentication
and the FastAPI/Pydantic/LangGraph stack plus bounded text-PDF parsing with pypdf.
Event consumption is disabled unless
`SMARTLECT_GROWTH_EVENTS_ENABLED=true`.

The launcher reads `run/runtime.env` and, for the Python application only,
the optional mode-600 `run/model.env`. The latter accepts only provider fields;
it cannot replace database, payment or internal authentication configuration.
These files are literal Python inputs, not shell scripts. F0 has copied the
authorized model fields and fixed `SMARTLECT_MODEL_ID=qwen3.7-plus`. See
`../artifacts/f2-provider-capabilities.json`, `../artifacts/f2-live-vertical-v6.json`,
`../docs/agent-design.md`, `../docs/adr/0001-final-integration.md` and
`../docs/integration-reuse.md` for decisions and source attribution.

Frozen source attribution and limitations are recorded in
`../docs/growth-migration.md`; original license material is under `licenses/`.
