# Smartlect Growth P0 migration

## Frozen inputs and provenance

Only the verified handoff snapshots were read. Build, imports and tests run from
`growth/`; the extracted sources are never put on `PYTHONPATH`.

| Frozen source | Commit | Reuse |
|---|---|---|
| `ads-python` | `04c5750a727f993617d368980a5b7937008d6226` | `python/src/tools/analytics.py` anomaly checks and bounded-budget intent; `python/src/models/schemas.py` campaign metrics structure |
| `recommendation-python` | `faf0fd8309c550426f3b2cce057dd4566e209e09` | `python/services/ab_test.py` deterministic hash assignment, posterior sampling and grouped statistics; all five assertions from `python/tests/test_ab_test.py` |

The advertising source's MIT license is copied verbatim to
`growth/licenses/ads-python-LICENSE`. The recommendation snapshot contains no
standalone LICENSE file; its README declares MIT and links the absent file.
That complete original README is retained under `growth/licenses/` as source
evidence. No replacement copyright holder or license text has been invented.
Its historical promotion and measurements are not Smartlect validation results.

## Changes and exclusions

- All imports use `smartlect.*`; distribution name is `smartlect-growth`. No
  top-level `models`, `agents`, `services`, `config`, or path insertion remains.
- The existing A/B implementation uses `random.betavariate`, `statistics` and
  dataclasses instead of NumPy. The five original checks retain their assertions;
  the unavailable default LLM treatment is named `treatment_content`. P0 stores
  experiment state only in memory and does not yet apply a group to recommendations.
- Metrics and budget configuration use integer cents; missing denominators return
  `None`. Decimal conversion rejects floats, nonfinite values and partial cents.
- B5 is replaced with bounded integer allocation without post-clamp normalization.
  Configured budget is separate from historical spend. Stockout proposes a pause
  and removes all future budget; impossible minima fail explicitly. Historical
  ROAS is only a baseline signal, with no optimization gain claim. Bound arithmetic
  uses exact `Fraction` values so global Decimal precision cannot round a cap upward.
- LLM constructors, LangGraph orchestration, static product lists, random reports,
  success-dictionary ad clients, ClickHouse/Milvus/Redis startup and old dashboard
  code are not migrated. Their known missing execution paths are not useful P0
  foundations. The in-memory feature store no-op fallback is likewise not copied;
  durable behavior facts belong to the later Java-event integration.
- `python -m smartlect.app --check` validates isolated configuration without a key.
  The P0 server serves `/health` only. Unknown model modes fail explicitly.
  It does not claim business readiness or actual model validation.

## Verification and next gate

Executed on 2026-09-09 in `/home/song/code/Smartlect`:

| Command | Actual result |
|---|---|
| `/home/song/miniconda3/bin/python --version` | Python 3.13.11; system Python 3.10.12 is below the package minimum and was not used to install/run it |
| `/home/song/miniconda3/bin/python -m venv growth/.venv` | Clean project-local virtual environment created, exit 0 |
| `growth/.venv/bin/python -m pip install ./growth` | Non-editable wheel built and installed with isolated pinned build dependency, exit 0 |
| `growth/.venv/bin/python -m pip install --force-reinstall ./growth` | Final modified sources rebuilt and installed, exit 0 |
| `growth/.venv/bin/python -m unittest discover -s growth/tests -v` | 12 checks passed: original 5 A/B checks plus 7 regression/smoke checks, exit 0 |
| `python3 -B scripts/check_independence.py --self-test` | Passed, including external root-directory links, symlinked Git directory and explicit removed-AI objects |
| `python3 -B scripts/check_independence.py` | Scanned 764 runtime files, zero naming/independence violations at review time |
| `growth/.venv/bin/python -m pip check` | No broken requirements, exit 0 |
| `/home/song/code/Smartlect/growth/.venv/bin/python -I -m smartlect.app --check` from `/tmp` | Independent installed-package import and mock config check passed, exit 0 |

The HTTP test starts the installed package with Python isolated mode (`-I`)
from a fresh temporary directory, waits for an actual `/health` response with
a bounded timeout, verifies an unimplemented endpoint returns 404, and terminates
only the process it created. No growth process remains running after verification.
No original project path, runtime, environment file, key, or extracted module was
used for build or test. The original directories were not physically hidden;
full-stack absence testing remains a P6 gate.

P1–P4 still require commerce APIs, durable facts/experiments, actual catalog and
SKU filtering, attribution/ledger, campaign execution and resulting observations.
No transaction database is read or written by this package. Real LLM capability,
recommendation effectiveness and ad feedback improvement have not been tested.
