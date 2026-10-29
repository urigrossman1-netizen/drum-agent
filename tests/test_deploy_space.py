"""scripts/deploy_space.py without a network: the Space's files, and how a deployment is
followed until the new build runs (the Hub's answers replayed by a stand-in)."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deploy_space", ROOT / "scripts" / "deploy_space.py")
deploy = importlib.util.module_from_spec(spec)
sys.modules["deploy_space"] = deploy
spec.loader.exec_module(deploy)


class Hub:
    def __init__(self, stages, host=None, subdomain=None):
        self.stages, self.host, self.subdomain = list(stages), host, subdomain

    def get_space_runtime(self, repo_id):
        stage = self.stages.pop(0) if len(self.stages) > 1 else self.stages[0]
        return SimpleNamespace(stage=stage, hardware="cpu-basic", raw={"errorMessage": "pip failed"})

    def space_info(self, repo_id):
        return SimpleNamespace(host=self.host, subdomain=self.subdomain)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(deploy.time, "sleep", lambda s: None)


def test_the_space_gets_what_the_dockerfile_copies(tmp_path):
    files = deploy.assemble(tmp_path, "https://github.com/o/r")
    for rel in ("Dockerfile", "pyproject.toml", "scripts/install_lilypond.sh", "drum_agent/web/app.py",
                "drum_agent/data/onset_classifier.npz", "examples/specs/03_full_song_northbound.yaml"):
        assert rel in files
    card = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert card.startswith("---\n") and "sdk: docker" in card and "app_port: 8000" in card
    assert not any("__pycache__" in f or f.endswith(".pyc") for f in files)


def test_waits_for_the_new_build_not_the_old_one():
    hub = Hub(["RUNNING", "RUNNING_BUILDING", "BUILDING", "APP_STARTING", "RUNNING"])
    deploy.wait_running(hub, "me/drum-agent", minutes=5)
    assert hub.stages == ["RUNNING"]


def test_an_old_error_is_not_this_builds_but_a_new_one_is():
    deploy.wait_running(Hub(["BUILD_ERROR", "BUILDING", "RUNNING"]), "me/drum-agent", minutes=5)
    with pytest.raises(SystemExit, match="BUILD_ERROR: pip failed"):
        deploy.wait_running(Hub(["RUNNING", "BUILDING", "BUILD_ERROR"]), "me/drum-agent", minutes=5)


def test_the_address():
    assert deploy.address(Hub([], host="https://me-drum-agent.hf.space"), "me/drum-agent") == "https://me-drum-agent.hf.space"
    assert deploy.address(Hub([], subdomain="me-drum-agent"), "me/drum-agent") == "https://me-drum-agent.hf.space"
    assert deploy.address(Hub([]), "Me/Drum_Agent") == "https://me-drum-agent.hf.space"
