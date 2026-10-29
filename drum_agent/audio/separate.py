"""Pull the drums out of a band mix before transcription, with HTDemucs.

HTDemucs (Rouard, Massa and Défossez, "Hybrid Transformers for Music Source Separation",
ICASSP 2023; MIT licence, https://github.com/adefossez/demucs) splits a mix into drums,
bass, vocals and other. Transcribing its drum stem instead of the mix keeps guitars, bass
and voices from being heard as strokes. It runs on the CPU. The Windows app and the server
image ship the model (about 80 MB) in $TORCH_HOME/hub/checkpoints, and it is loaded from
there; elsewhere demucs downloads it the first time it is used (from the Hugging Face Hub,
or its older address) and caches it.

Optional: `available()` is False without the `demucs` package. Whether it is used is
decided by measurement on real recordings (scripts/eval_real.py --separate, docs/MODELS.md),
not assumed.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import numpy as np

MODEL = "htdemucs"
# The weights as demucs' model list names them (the dash is followed by the start of their
# SHA-256), shipped beside `htdemucs.yaml`, the one-model bag: models: ['955717e8'].
WEIGHTS = "955717e8-8726e21a.th"
_model = None


def shipped() -> Path | None:
    """The folder holding a shipped copy of the model ($TORCH_HOME/hub/checkpoints), if complete.

    demucs looks for the model on the Hugging Face Hub first and downloads it from there
    whatever is on disk, so a shipped copy is loaded from its own folder (`get_model(repo=)`,
    which checks the weights' SHA-256): no download, and it works offline."""
    home = os.environ.get("TORCH_HOME") or Path(os.environ.get("XDG_CACHE_HOME") or "~/.cache").expanduser() / "torch"
    folder = Path(home) / "hub" / "checkpoints"
    return folder if (folder / WEIGHTS).is_file() and (folder / f"{MODEL}.yaml").is_file() else None


def available() -> bool:
    return importlib.util.find_spec("demucs") is not None and importlib.util.find_spec("torch") is not None


def _get():
    global _model
    if _model is None:
        import torch
        from demucs.pretrained import get_model
        threads = int(os.environ.get("DRUM_AGENT_TORCH_THREADS", "0"))
        if threads > 0:
            torch.set_num_threads(threads)
        folder = shipped()
        _model = get_model(MODEL, repo=folder) if folder else get_model(MODEL)
        _model.eval()
    return _model


def separate_drums(y: np.ndarray, sr: int) -> np.ndarray:
    """The drum stem of a mono mix `y` at rate `sr` (same rate and length back)."""
    import librosa
    import torch
    from demucs.apply import apply_model

    model = _get()
    rate = model.samplerate
    x = y.astype(np.float32)
    if sr != rate:
        x = librosa.resample(x, orig_sr=sr, target_sr=rate)
    wav = torch.from_numpy(np.stack([x, x]))
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8  # the normalization demucs' own command uses
    with torch.no_grad():
        out = apply_model(model, ((wav - mean) / std)[None], split=True, overlap=0.25, progress=False,
                          device="cpu")[0]
    drums = (out[model.sources.index("drums")] * std + mean).mean(0).numpy()
    if sr != rate:
        drums = librosa.resample(drums, orig_sr=rate, target_sr=sr)
    n = len(y)
    return np.pad(drums, (0, max(0, n - len(drums))))[:n].astype(np.float32)
