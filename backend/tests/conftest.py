import os

# SQLite keeps the default suite portable. Set TEST_DATABASE_URL for PostgreSQL.
# This must be a disposable database: the fixture clears its tables.
os.environ['DATABASE_URL'] = os.environ.get('TEST_DATABASE_URL', 'sqlite+pysqlite:///:memory:')
os.environ['INSTRUCTOR_SECRET'] = 'classroom-test-instructor-key'

import pytest
from sqlalchemy.engine import make_url

# Destructive fixtures accept only databases explicitly named as tests.
_test_url = make_url(os.environ['DATABASE_URL'])
if _test_url.get_backend_name() != 'sqlite' and 'test' not in (_test_url.database or '').lower():
    raise RuntimeError('TEST_DATABASE_URL must name a disposable test database.')
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base, get_db
from backend.app.main import app


@pytest.fixture
def client():
    url = os.environ['DATABASE_URL']
    options = {'connect_args': {'check_same_thread': False}, 'poolclass': StaticPool} if url.startswith('sqlite') else {}
    engine = create_engine(url, **options)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)

    def override():
        with maker() as db:
            yield db
    app.dependency_overrides[get_db] = override
    # Lifespan is not needed: schema is initialized explicitly on the test engine.
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
