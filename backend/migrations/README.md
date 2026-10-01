# Database migrations

`versions/0001_current_schema.py` is the adoption baseline for every table that
existed in Lemma 0.2 when migrations were introduced. It deliberately tolerates
an existing table so development and installed databases created by the former
`SQLModel.metadata.create_all()` startup path can be adopted without losing data.

After changing models, create and review a revision from `backend/`:

```bash
uv run alembic revision --autogenerate -m "describe the schema change"
uv run python -m app.db_admin migrate
```

Never edit a released revision or reuse an application version for a different
schema. Startup automatically makes and verifies an online SQLite backup before
applying any pending revision to a non-empty database. Use the maintenance command,
not a direct `alembic upgrade`, so the backup and single-process lock cannot be skipped.
