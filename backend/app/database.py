import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', override=False)


def database_url(include_database=True):
    if os.getenv('DATABASE_URL') and include_database:
        return os.environ['DATABASE_URL']
    if os.getenv('DB_DRIVER', 'mysql') == 'sqlite':
        (ROOT / 'runtime').mkdir(exist_ok=True)
        return f"sqlite:///{ROOT / 'runtime' / 'career.db'}"
    return URL.create(
        'mysql+pymysql', username=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''), host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '3306')),
        database=os.getenv('DB_NAME', 'career_platform') if include_database else None,
        query={'charset': 'utf8mb4'},
    )


class Base(DeclarativeBase):
    pass


engine = create_engine(database_url(), pool_pre_ping=True)
if engine.dialect.name == 'sqlite':
    @event.listens_for(engine, 'connect')
    def enable_foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db
