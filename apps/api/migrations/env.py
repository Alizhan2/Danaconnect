"""Alembic entrypoint; reads the same DATABASE_URL as the API."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.schema_registry import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=settings.database_url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def migrate_connection(connection):
    context.configure(connection=connection, target_metadata=target_metadata,
                      compare_type=True, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # An operator can hold its PostgreSQL transaction, revision check and
    # advisory lock on the same physical connection as these migrations.
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        migrate_connection(supplied_connection)
        return
    connectable = engine_from_config(config.get_section(config.config_ini_section),
                                    prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
        migrate_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
