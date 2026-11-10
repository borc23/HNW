# housing-netherlands

Personal housing dashboard for the Dutch rental market: collects, enriches and ranks listings.

## Development

```bash
uv sync
uv run pre-commit install
uv run pytest -m "not integration"
```

CI runs ruff and the unit tests on every push to `main` and on pull requests.
