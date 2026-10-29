# Agent / Copilot instructions for pg-spot-operator

Python (3.x) operator that keeps single-node PostgreSQL instances running on cheap AWS Spot VMs. It is driven by YAML "manifests", provisions VMs with boto3, then configures them with Ansible.

## Build, lint, test

Use the Makefile (prefers `.venv/bin/` if present):

- `make virtualenv` / `make install` – create venv, `pip install -e .[test]`
- `make fmt` – isort + `black -l 79` (line length is **79**)
- `make lint` – `flake8 --ignore=E501,W503`, `black -l 79 --check` (package and tests), `mypy --ignore-missing-imports pg_spot_operator/`
- `make test` – runs lint first, then `pytest -v --cov ... --maxfail=1 tests/`
- Single test: `.venv/bin/pytest -v tests/test_manifests.py::test_name` (or `-k expr`)

CI (`.github/workflows/main.yml`) runs `make lint` and `make test`. Commits follow Conventional Commits; releases via `make release` (writes `pg_spot_operator/VERSION`, regenerates `HISTORY.md`). CONTRIBUTING.md asks for tests with every change and docs updates (`docs/`, mkdocs).

## Architecture

- `cli.py` / `__main__.py` – argparse (all options also available as env vars) and entrypoint; builds an `InstanceManifest` from a manifest file/string or CLI flags.
- `manifests.py` – `InstanceManifest` model, validation and defaults for the user-facing manifest (see `example_manifests/` and `docs/`). New manifest options must be added here and documented.
- `operator.py` – core logic and `do_main_loop`: reconciles desired state (manifest) vs. reality. Handles `ensure_vm`, `destroy_instance`, `teardown_region`, expiration, backups (pgBackRest/S3), connstr publishing, and running Ansible "actions" (`run_action`, `run_ansible_handler`) in a temp workdir under `~/.pg-spot-operator/`, with generated inventory and run script.
- `cloud_api.py` + `cloud_impl/` – cloud abstraction; only AWS implemented (`aws_client`, `aws_spot` for pricing/instance type info, `aws_vm`, `aws_s3`, `aws_cache`, `cloud_structs`, `cloud_util`).
- `instance_type_selection.py` – picks the cheapest matching Spot SKU per selection strategy from manifest HW requirements; `pgtuner.py` – derives Postgres config from the chosen instance's resources, merged with non-conflicting user config.
- `cmdb.py` + `cmdb_impl/` – local SQLite CMDB of instances/VMs/manifests. Schema is **roll-forward only**: append new entries to `DDL_MIGRATIONS` in `sqlite_migrations.py` (applied by `schema_manager.py`); never edit existing migrations.
- `ansible/v1/` – playbooks/roles used for VM setup (OS, Postgres, pgBackRest, monitoring, self-termination); the operator copies these into per-action temp dirs and runs them over SSH. `constants.py` holds shared constants (action names, manifest section keys, tags).
- Other dirs: `k8s/` (deployment), `scripts/` (AWS/terraform/smoke testing), `Containerfile`/`entrypoint.sh`.

## Conventions

- Tests live in `tests/` (flat `test_<module>.py`); `conftest.py` auto-chdirs each test into a tmpdir. Tests mock cloud/AWS calls rather than hitting AWS.
- Cloud resources created by the operator are identified via tags (e.g. `SPOT_OPERATOR_EXPIRES_TAG`) – keep tagging consistent when touching VM/volume/address logic, since cleanup relies on it.
- Type hints are expected (mypy runs in lint); module-level `logger = logging.getLogger(__name__)`.
- Keep code as simple as possible (KISS): prefer the straightforward solution, avoid unnecessary abstractions, indirection or speculative generality.
