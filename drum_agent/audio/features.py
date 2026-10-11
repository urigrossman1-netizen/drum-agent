"""Shared spectral front end."""

from __future__ import annotations

import numpy as np

SR = 44100
N_FFT = 2048
HOP = 256  # 5.8 ms
N_BANDS = 96
FMIN = 30.0
FMAX = 17000.0


def frame_time(frames: np.ndarray | int) -> np.ndarray | float:
    return np.asarray(frames) * HOP / SR


def filterbank() -> np.ndarray:
    import librosa
    return librosa.filters.mel(sr=SR, n_fft=N_FFT, n_mels=N_BANDS, fmin=FMIN, fmax=FMAX, htk=True, norm=None)


_FB = None


def band_spectrogram(y: np.ndarray) -> np.ndarray:
    """Magnitude spectrogram on a mel filterbank: (bands, frames), non-negative."""
    import librosa
    global _FB
    if _FB is None:
        _FB = filterbank()
    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP, center=True, window="hann"))
    return (_FB @ S).astype(np.float32)


def band_centers() -> np.ndarray:
    import librosa
    return librosa.mel_frequencies(n_mels=N_BANDS + 2, fmin=FMIN, fmax=FMAX, htk=True)[1:-1]


STACK = (0, 3, 8)  # frame offsets stacked into one NMF column (0, +17 ms, +46 ms)


def stack_frames(V: np.ndarray, offsets: tuple[int, ...] = STACK) -> np.ndarray:
    """Stack each frame with later frames so templates encode attack and decay shape."""
    F, T = V.shape
    out = np.zeros((F * len(offsets), T), dtype=V.dtype)
    for i, o in enumerate(offsets):
        out[i * F:(i + 1) * F, :T - o] = V[:, o:]
    return out
