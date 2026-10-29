"""Which HTDemucs model the separation loads: the copy shipped with the Windows app and the
server image ($TORCH_HOME/hub/checkpoints, with its bag file) is loaded from its folder, so
nothing is downloaded; without one, demucs fetches the model itself. demucs and PyTorch are
stood in for (their model is measured in scripts/eval_real.py)."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from drum_agent.audio import separate


@pytest.fixture
def demucs(monkeypatch):
    calls = []
    pretrained = ModuleType("demucs.pretrained")
    pretrained.get_model = lambda name, repo=None: calls.append((name, repo)) or SimpleNamespace(eval=lambda: None)
    monkeypatch.setitem(sys.modules, "demucs", ModuleType("demucs"))
    monkeypatch.setitem(sys.modules, "demucs.pretrained", pretrained)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda n: None))
    monkeypatch.setattr(separate, "_model", None)
    return calls


def test_a_shipped_copy_is_loaded_from_its_folder(tmp_path, monkeypatch, demucs):
    folder = tmp_path / "hub" / "checkpoints"
    folder.mkdir(parents=True)
    (folder / separate.WEIGHTS).write_bytes(b"weights")
    monkeypatch.setenv("TORCH_HOME", str(tmp_path))
    assert separate.shipped() is None  # the weights alone are not enough: demucs needs the bag file
    (folder / "htdemucs.yaml").write_text("models: ['955717e8']\n", encoding="utf-8")
    assert separate.shipped() == folder
    separate._get()
    assert demucs == [("htdemucs", folder)]


def test_without_a_shipped_copy_demucs_fetches_the_model(tmp_path, monkeypatch, demucs):
    monkeypatch.setenv("TORCH_HOME", str(tmp_path))
    assert separate.shipped() is None
    separate._get()
    assert demucs == [("htdemucs", None)]
