import pytest

from agila import db

TEST_DB = "agila_test"


def _recreate_test_database():
    assert TEST_DB == "agila_test"  # never drop anything else
    with db.connect(dbname="postgres", register=False) as admin:
        admin.autocommit = True
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")


@pytest.fixture
def empty_db():
    """Name of a fresh, empty database; dropped afterwards. Never touches `agila`."""
    _recreate_test_database()
    yield TEST_DB
    with db.connect(dbname="postgres", register=False) as admin:
        admin.autocommit = True
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


@pytest.fixture
def conn(empty_db):
    with db.connect(dbname=empty_db, register=False) as plain:
        db.migrate(plain)
    with db.connect(dbname=empty_db) as migrated:
        yield migrated
