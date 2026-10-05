import pytest

from bridge import config, db

# 실제 data/private/(커밋하지 않는 회사 보고서, spec 2-4-1) 경로. 그 데이터를 쓰는 테스트만 이 값으로 되돌린다.
REAL_PRIVATE_RESULTS_DIR = config.PRIVATE_RESULTS_DIR


@pytest.fixture(scope="session", autouse=True)
def _no_private_results(tmp_path_factory):
    """테스트 결과가 로컬에만 있는 비공개 데이터에 따라 달라지지 않게 기본으로 끈다."""
    config.PRIVATE_RESULTS_DIR = tmp_path_factory.mktemp("no_private") / "none"
    yield
    config.PRIVATE_RESULTS_DIR = REAL_PRIVATE_RESULTS_DIR


@pytest.fixture(scope="session")
def loaded_db(tmp_path_factory):
    """샘플 전체를 적재한 임시 DB (실제 bridge.db는 건드리지 않는다)."""
    path = tmp_path_factory.mktemp("db") / "bridge.db"
    db.init(path)
    conn = db.connect(path)
    yield conn
    conn.close()
