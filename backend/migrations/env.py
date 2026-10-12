from alembic import context
from app.database import Base, engine
from app import models  # noqa: F401 - register metadata

if context.is_offline_mode():
    raise RuntimeError('Use online migrations with the configured local database')
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
