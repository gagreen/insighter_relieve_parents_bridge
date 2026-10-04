import pytest

from bridge import db


@pytest.fixture(scope="session")
def loaded_db(tmp_path_factory):
    """샘플 전체를 적재한 임시 DB (실제 bridge.db는 건드리지 않는다)."""
    path = tmp_path_factory.mktemp("db") / "bridge.db"
    db.init(path)
    conn = db.connect(path)
    yield conn
    conn.close()
