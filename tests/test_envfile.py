"""The settings file the studio and the desktop app read (drum_agent/envfile.py)."""

from drum_agent.envfile import default_env_file, load_env_file, parse


def test_parse_handles_comments_quotes_export_and_inline_comments():
    text = (
        "# a comment\n"
        "\n"
        "YOUTUBE_API_KEY=abc123\n"
        "export SPOTIFY_CLIENT_ID='id with spaces'\n"
        'SPOTIFY_CLIENT_SECRET="s#cret"\n'
        "DRUM_AGENT_MAX_UPLOAD_MB=50 # smaller uploads\n"
        "not an assignment\n"
        "9BAD=1\n"
        "ANTHROPIC_API_KEY=\n"
    )
    got = parse(text)
    assert got["YOUTUBE_API_KEY"] == "abc123"
    assert got["SPOTIFY_CLIENT_ID"] == "id with spaces"
    assert got["SPOTIFY_CLIENT_SECRET"] == "s#cret"          # quoted: the # is part of the value
    assert got["DRUM_AGENT_MAX_UPLOAD_MB"] == "50"           # unquoted: " # ..." is a comment
    assert got["ANTHROPIC_API_KEY"] == ""
    assert set(got) == {"YOUTUBE_API_KEY", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET",
                        "DRUM_AGENT_MAX_UPLOAD_MB", "ANTHROPIC_API_KEY"}  # no "9BAD", no prose line


def test_load_sets_only_missing_non_empty_app_settings(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "YOUTUBE_API_KEY=from-file\n"
        "SPOTIFY_CLIENT_ID=from-file\n"
        "ANTHROPIC_API_KEY=\n"
        "PATH=C:\\evil\n"
        "PYTHONPATH=x\n",
        encoding="utf-8",
    )
    env = {"SPOTIFY_CLIENT_ID": "from-environment"}
    res = load_env_file(f, env)
    assert env["YOUTUBE_API_KEY"] == "from-file"
    assert env["SPOTIFY_CLIENT_ID"] == "from-environment"      # the environment wins
    assert "ANTHROPIC_API_KEY" not in env                       # empty means not configured
    assert "PATH" not in env and "PYTHONPATH" not in env        # never anything but app settings
    assert res.loaded == ["YOUTUBE_API_KEY"]
    assert res.kept == ["SPOTIFY_CLIENT_ID"]
    assert sorted(res.ignored) == ["PATH", "PYTHONPATH"]


def test_summary_never_contains_values(tmp_path):
    f = tmp_path / "settings.env"
    f.write_text("ANTHROPIC_API_KEY=sk-secret-value\n", encoding="utf-8")
    res = load_env_file(f, {})
    assert "sk-secret-value" not in res.summary()
    assert "1 setting(s)" in res.summary()


def test_missing_file_and_utf8_bom(tmp_path):
    assert load_env_file(tmp_path / "nope.env", {}).loaded == []
    f = tmp_path / "bom.env"
    f.write_bytes("\ufeffYOUTUBE_API_KEY=k\n".encode("utf-8"))
    env: dict = {}
    load_env_file(f, env)
    assert env == {"YOUTUBE_API_KEY": "k"}                     # Notepad's BOM doesn't hide the first name


def test_a_leading_tilde_is_the_home_folder(tmp_path, fake_home):
    f = tmp_path / ".env"
    f.write_text("DRUM_AGENT_DATA_DIR=~/.drum_agent/web\nDRUM_AGENT_MUSIC_DIRS=D:/Music~old\n", encoding="utf-8")
    env: dict = {}
    load_env_file(f, env)
    assert env["DRUM_AGENT_DATA_DIR"] == str(fake_home) + "/.drum_agent/web"  # not a folder named "~"
    assert env["DRUM_AGENT_MUSIC_DIRS"] == "D:/Music~old"                      # only a leading ~ counts


def test_the_studio_data_folder_expands_a_tilde(monkeypatch, fake_home):
    from pathlib import Path

    from drum_agent.web.store import default_data_dir
    monkeypatch.setenv("DRUM_AGENT_DATA_DIR", "~/studio-data")
    assert default_data_dir() == Path(str(fake_home) + "/studio-data")


def test_default_env_file_prefers_the_named_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DRUM_AGENT_ENV_FILE", raising=False)
    assert default_env_file(tmp_path / ".env") == tmp_path / ".env"
    monkeypatch.setenv("DRUM_AGENT_ENV_FILE", str(tmp_path / "other.env"))
    assert default_env_file(tmp_path / ".env") == tmp_path / "other.env"
