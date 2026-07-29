from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context

os.environ["QUANTHUB_SKIP_STORE_INIT"] = "1"

from apps.api import database, models, store  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = database.database_url(store._DB)
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=models.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Revision 0001 adopts the exact schema currently initialized by the application.
    store._init()
    engine = database.engine_for(store._DB)
    models.refresh_metadata(engine)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=models.metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
