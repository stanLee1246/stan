import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.getenv('TEST_MYSQL') == '1':
    # A dedicated disposable database, never the application database.
    os.environ.pop('DATABASE_URL', None)
    os.environ['DB_NAME'] = 'career_platform_tests'
else:
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(__file__).resolve().parents[1] / 'runtime' / 'test.db')
    Path(__file__).resolve().parents[1].joinpath('runtime').mkdir(exist_ok=True)

from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine
from app.main import app
from app.cli import migrate
from app.models import User
from app.security import hash_password


@pytest.fixture(scope='session', autouse=True)
def prepare_database():
    migrate()


@pytest.fixture()
def client():
    assert engine.dialect.name == 'sqlite' or engine.url.database == 'career_platform_tests'
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(User(username='admin_user', nickname='测试管理员', role='admin', password_hash=hash_password('AdminTesting123!')))
        db.commit()
    with TestClient(app) as c:
        yield c


def login_as(client, username='student_user'):
    client.post('/api/auth/register', json={'username': username, 'nickname': '测试学生', 'password': 'StudentTesting123!'})
    r = client.post('/api/auth/login', json={'username': username, 'password': 'StudentTesting123!'})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['token']}


@pytest.fixture()
def student(client):
    return login_as(client)


@pytest.fixture()
def admin(client):
    r = client.post('/api/auth/login', json={'username': 'admin_user', 'password': 'AdminTesting123!'})
    return {'Authorization': 'Bearer ' + r.json()['token']}
