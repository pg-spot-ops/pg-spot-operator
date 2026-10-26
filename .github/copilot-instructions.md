# Copilot Instructions for pg-spot-operator

## Build, Test & Lint Commands

### Setup
```bash
make virtualenv          # Create Python virtual environment
source .venv/bin/activate
make install            # Install package in development mode
```

### Development Workflow
```bash
make fmt                # Format code (black @ 79 chars, isort)
make lint               # Run pep8 (flake8), black, mypy type checks
make test               # Run tests + coverage report (requires 100% coverage)
make watch              # Watch files and re-run tests on changes
```

### Single Test Execution
```bash
pytest -vv tests/test_manifests.py::test_function_name
pytest -vv tests/test_aws_spot.py -k "keyword_to_filter_tests"
```

### Documentation
```bash
make docs               # Build mkdocs locally (opens in browser)
```

### Release
```bash
make release            # Creates semantic version tag and pushes to remote
                        # Uses conventional commits to auto-generate changelog
```

## High-Level Architecture

This is a Python-based operator that manages stateful PostgreSQL databases on AWS Spot instances, providing cost savings (~5x vs RDS) by leveraging cheap but interruptible compute.

### Core Components

**CLI Entry Point** (`pg_spot_operator/cli.py`)
- TAP-based argument parser that translates CLI flags to manifest configuration
- Handles all user inputs and routes to appropriate operations

**Manifest System** (`pg_spot_operator/manifests.py`)
- YAML-based declarative configuration (desired state)
- Uses Pydantic for validation with custom YAML tag support (!vault for encrypted secrets)
- Sections: cloud, region, instance_name, postgres (version, tuning, extensions, config), vm (hardware specs), os, user_tags

**CMDB (Configuration Management Database)** (`pg_spot_operator/cmdb.py`)
- SQLAlchemy ORM models: `Instance`, `Vm`, `ManifestSnapshot`, `IgnoredInstance`
- State persistence in SQLite (the default) or PostgreSQL
- Tracks desired manifest snapshots and actual VM state
- Provides helper functions for connection strings and instance queries

**Operator Loop** (`pg_spot_operator/operator.py`)
- Main reconciliation engine: compares desired (manifest) vs actual (cloud) state
- Handles instance lifecycle: creation, configuration, updates, termination
- Manages Spot interruption resilience (signaling volumes, replicas, backups)
- S3 integration for backup storage and secret management

**Cloud API Abstraction** (`pg_spot_operator/cloud_api.py`)
- Pricing API: resolves hardware requirements to instance types and regions
- Instance type selection strategies (balanced, cheapest, etc.)
- Cloud provider detection and routing

**AWS Implementation** (`pg_spot_operator/cloud_impl/`)
- `aws_spot.py` - Spot pricing, instance queries, eviction rates
- `aws_vm.py` - VM provisioning, volume management, network interfaces
- `aws_s3.py` - S3 bucket management for backups
- `aws_client.py` - Credential handling and session management
- `cloud_structs.py` - Shared data classes (InstanceTypeInfo, CloudVM, etc.)

### Data Flow
1. User provides manifest + CLI args → merged into canonical manifest
2. Operator reads/writes manifest snapshots to CMDB
3. Cloud API resolves desired specs (CPU, RAM, storage) → actual instance types
4. AWS provider provisions/updates VMs, volumes, security groups
5. Ansible playbooks configure PostgreSQL on provisioned VM
6. Operator monitors state and handles interruptions

## Key Conventions

### Code Structure
- **Line length**: 79 characters (enforced by black, flake8 E501 ignored in lint config)
- **Imports**: Organized via isort (stdlib → third-party → local)
- **Type hints**: Required; mypy type checking enforced in lint
- **Docstrings**: Not enforced but module/class docstrings should explain purpose

### Manifest & Configuration
- YAML format with custom `!vault` tag for encrypted secrets
- Manifest sections are strict Pydantic models with validation
- Defaults are sensible (postgres: version 15, vm.storage_type: network, etc.)
- Instance types resolved via AWS pricing API; SKU validation required

### Database Models (CMDB)
- SQLAlchemy declarative models inherit from `Base`
- JSON fields used for flexible structure (cloud metadata, instance details)
- DateTime fields use UTC timezone (`datetime.now(tz=tzutc())`)
- Snapshots track manifest changes for diffing/rollback

### Testing
- Test files mirror module names: `tests/test_*.py` for each `pg_spot_operator/*.py`
- **100% coverage required** (enforced via `make test`)
- Use pytest fixtures from `conftest.py` (mocking AWS calls, temp DBs)
- Test manifest parsing in `test_manifests.py` before integrating into operator tests

### Error Handling
- Exceptions propagate with context; wrap with logging for diagnostics
- AWS API errors: check for transient (retry) vs permanent (fail fast)
- Manifest validation: Pydantic raises `ValidationError` with detailed field paths
- State conflicts: log both desired and actual, fail safe to prevent data loss

### Git & Release
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  - Examples: `feat(cmdb): add replica state tracking`, `fix(operator): handle spot interruption race`, `docs: update backup section`
- PR reviews check for 100% test coverage and linter passing
- Releases use `make release` which auto-generates HISTORY.md from conventional commits

### Logging
- Use module-level logger: `logger = logging.getLogger(__name__)`
- Levels: DEBUG (verbose internal state), INFO (key actions), WARNING (recoverable issues), ERROR (failures)
- Sensitive data (passwords, keys) must be redacted in logs

### Constants
- Centralized in `pg_spot_operator/constants.py` (CLOUD_AWS, BACKUP_TYPE_*, etc.)
- Avoid magic strings/numbers in code; reference constants instead

### Dependencies
- Core: boto3 (AWS), pydantic (validation), sqlalchemy (ORM), pyyaml, requests, humanize, prettytable
- Testing: pytest, pytest-cov, coverage, mypy, flake8, black, isort
- Docs: mkdocs
- CLI: typed-argument-parser (TAP)

### Ansible Integration
- Playbooks in `ansible/` directory (not Kubernetes-native; runs over SSH)
- VM hostname/IP resolved by operator and passed to playbook execution
