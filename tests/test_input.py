"""PoC2-01 입력 검증 [P-01]."""
import pytest

from bridge import config
from bridge.rules.input import check_input


@pytest.mark.parametrize("text", ["", "   ", "\n\t  \n"])
def test_poc2_01_empty_input_is_not_processed(text):
    r = check_input(text)
    assert (r.ok, r.reason) == (False, "empty")
    assert r.message


def test_poc2_01_max_length_is_accepted():
    r = check_input("가" * config.MAX_INPUT_CHARS)
    assert (r.ok, r.reason, r.message) == (True, None, None)


def test_poc2_01_over_max_length_asks_to_split():
    r = check_input("가" * (config.MAX_INPUT_CHARS + 1))
    assert (r.ok, r.reason) == (False, "too_long")
    assert "1,000" in r.message
    assert "{" not in r.message


def test_poc2_01_length_ignores_surrounding_whitespace():
    assert check_input("  " + "가" * config.MAX_INPUT_CHARS + "\n").ok
