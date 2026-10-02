# Database lifecycle

Run commands from `apps/api` with its activated virtual environment.

1. Copy `apps/api/.env.example` to `apps/api/.env` and choose `DATABASE_URL`.
2. Run `python -m alembic upgrade head` to create or upgrade the schema.
3. For synthetic development records, explicitly set `ENVIRONMENT=development`
   and `DEMO_MODE=true`, then run `python -m app.seed`.
4. Optional repeatable date: `python -m app.seed --reference-date 2026-10-01`.
   UUIDs are stable. Re-running never overwrites profiles, states or consents.
5. Sign in using `admin@example.test`, `mentor@example.test` or
   `mentee@example.test` through the development code flow. Code display requires
   `AUTH_DEBUG_CODE=true`; the seed does not create passwords or sessions.

`python -m app.seed --create-tables` is a development convenience for an empty
disposable database. It does not mark Alembic's version and should not be mixed
with migration management. Normal API startup never creates or seeds tables.

The baseline migration is a frozen schema snapshot. Subsequent schema changes
need new reviewed revisions (`python -m alembic revision --autogenerate -m ...`).
For PostgreSQL, use a `postgresql+psycopg://` DATABASE_URL. Never seed a production
or real-user database. Demo documents are clearly marked nonlegal drafts.

Database constraints enforce scheduled-booking slot uniqueness, pending direct
and project application uniqueness (separate indexes handle NULL project IDs),
active participation uniqueness, consent and membership uniqueness, rating
ranges, valid states and positive slot intervals. Partial unique indexes work
on both SQLite and PostgreSQL. Cross-row limits (mentor/project capacity,
overlapping slot intervals and participant role checks) are enforced by domain
routes under transaction locks; a simple row CHECK cannot enforce these rules.

Run the disposable database checks with `python -m migrations.check_invariants`.
This checks idempotence, profile preservation, UTC round trips, foreign keys,
nullable uniqueness and duplicate application/booking rejection. It does not
modify the configured database. Run `python -m alembic check` after upgrading to
confirm that the baseline and the ORM schema agree.

UTCDateTime maps timezone-aware timestamps to UTC. SQLite stores naive UTC and
returns aware UTC in application reads; PostgreSQL uses timestamp with timezone.
The migration intentionally stores no application callable defaults. ORM writes
set UUIDs and timestamps, so raw SQL inserts must supply them explicitly.
