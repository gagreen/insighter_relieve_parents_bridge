"""`.env` 로드 (CLAUDE.md 9장: 평가자가 `.env`에 API 키만 넣고 실행)."""
from bridge import config


def _write(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_env_file_sets_unset_variables(tmp_path, monkeypatch):
    monkeypatch.delenv("BRIDGE_T_A", raising=False)
    monkeypatch.delenv("BRIDGE_T_B", raising=False)
    path = _write(tmp_path, "# 주석\n\nBRIDGE_T_A=hello\nexport BRIDGE_T_B = 'quoted value'\n")
    assert config.load_env_file(path) == {"BRIDGE_T_A": "hello", "BRIDGE_T_B": "quoted value"}
    assert config.os.environ["BRIDGE_T_A"] == "hello"
    assert config.os.environ["BRIDGE_T_B"] == "quoted value"


def test_env_file_does_not_override_existing_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_T_A", "from-shell")
    path = _write(tmp_path, "BRIDGE_T_A=from-file\n")
    assert config.load_env_file(path) == {}
    assert config.os.environ["BRIDGE_T_A"] == "from-shell"


def test_env_file_keeps_colons_and_equals_in_value(tmp_path, monkeypatch):
    """ANTHROPIC_CUSTOM_HEADERS 같은 'name: value' 값을 그대로 둔다."""
    monkeypatch.delenv("BRIDGE_T_H", raising=False)
    path = _write(tmp_path, 'BRIDGE_T_H="anthropic-workspace-id: wrkspc_x=1"\n')
    config.load_env_file(path)
    assert config.os.environ["BRIDGE_T_H"] == "anthropic-workspace-id: wrkspc_x=1"


def test_empty_value_is_not_set(tmp_path, monkeypatch):
    """.env.example를 그대로 복사한 빈 키가 '빈 문자열 키'로 들어가지 않게 한다."""
    monkeypatch.delenv("BRIDGE_T_E", raising=False)
    path = _write(tmp_path, "BRIDGE_T_E=\n")
    assert config.load_env_file(path) == {}
    assert "BRIDGE_T_E" not in config.os.environ


def test_missing_env_file_is_ignored(tmp_path):
    assert config.load_env_file(tmp_path / "none.env") == {}


def test_malformed_lines_are_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("BRIDGE_T_OK", raising=False)
    path = _write(tmp_path, "그냥 문장\n=값만\nBRIDGE_T_OK=1\n")
    assert config.load_env_file(path) == {"BRIDGE_T_OK": "1"}
