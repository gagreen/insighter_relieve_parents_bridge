"""민감 정보 점검 [specs/poc.md 6-4, CLAUDE.md 11장]. 제출 전 공개 리포지토리에 들어가면 안 되는 것을 막는다."""
import json
import re
import subprocess

import pytest

from conftest import REAL_PRIVATE_RESULTS_DIR
from bridge import config

KEY_PATTERNS = {
    "anthropic": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "openai": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "google": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
}
FORBIDDEN_PREFIXES = ("docs/", "data/private/", "eval/reports/private/")
FORBIDDEN_NAMES = re.compile(r"(^|/)\.env$|\.db$|\.db-journal$")


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=config.ROOT, capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git 저장소가 아님")
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def _texts(tracked):
    for rel in tracked:
        path = config.ROOT / rel
        if not path.is_file():                     # 지웠지만 아직 커밋하지 않은 파일
            continue
        try:
            yield rel, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def test_6_4_forbidden_paths_not_tracked(tracked):
    assert [p for p in tracked if p.startswith(FORBIDDEN_PREFIXES) or FORBIDDEN_NAMES.search(p)] == []


def test_6_4_no_pdf_tracked(tracked):
    """과제 안내문·CBCL 보고서 PDF는 '지원자 외 공유 금지' (CLAUDE.md 11장)."""
    assert [p for p in tracked if p.lower().endswith(".pdf")] == []


def test_6_4_no_api_keys_in_tracked_files(tracked):
    hits = [(rel, name) for rel, text in _texts(tracked) for name, pat in KEY_PATTERNS.items() if pat.search(text)]
    assert hits == []


def test_6_4_private_report_child_name_not_tracked(tracked):
    """로컬에 회사 제공 원본 보고서(data/private/)가 있으면 그 아동 이름이 추적 파일 어디에도 없다."""
    files = sorted(REAL_PRIVATE_RESULTS_DIR.glob("*.json")) if REAL_PRIVATE_RESULTS_DIR.exists() else []
    if not files:
        pytest.skip("로컬에 회사 제공 원본 보고서 없음")
    names = {json.loads(f.read_text(encoding="utf-8"))["subject"]["name"] for f in files}
    hits = [(rel, n) for rel, text in _texts(tracked) for n in names if n and n in text]
    assert hits == []


def test_6_4_key_patterns_detect_examples():
    assert KEY_PATTERNS["anthropic"].search("sk-ant-api03-" + "a" * 30)
    assert KEY_PATTERNS["google"].search("AIza" + "B" * 35)
    assert not any(p.search("ANTHROPIC_API_KEY=") for p in KEY_PATTERNS.values())
