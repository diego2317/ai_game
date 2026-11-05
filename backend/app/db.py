import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

url = os.environ.get('DATABASE_URL', '')
if not url:
    raise RuntimeError('Set DATABASE_URL to a PostgreSQL connection URL. See README.md.')
if url.startswith(('postgres://', 'postgresql://')):
    url = 'postgresql+psycopg://' + url.split('://', 1)[1]
engine = create_engine(url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as session:
        yield session
