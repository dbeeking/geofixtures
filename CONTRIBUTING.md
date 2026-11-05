# Contributing

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check src tests
ruff format --check src tests
mypy src/geofixtures
```

## Adding a case

One case per pull request. Follow [docs/fixture-authoring.md](docs/fixture-authoring.md), and include
the derivation, tests for new oracle code, the updated catalog lock, and `docs/cases.md`.

## Oracle review

Someone other than the author checks a derivation before its review status changes. With a second
active maintainer, changes to approved oracles need two approvals.

## Data

Third-party data needs documented redistribution rights. See
[docs/reference-data-policy.md](docs/reference-data-policy.md).

## Labels

`good first issue`, `new fixture`, `oracle review`, `adapter`, `docs`, `performance`, `format support`,
`bug`. Narrow cases, such as a ring defect or density shortfall, make good first issues.
