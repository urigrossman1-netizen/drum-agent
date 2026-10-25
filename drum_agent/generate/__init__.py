"""Original beats from a description: `interpret` a prompt into a `BeatSpec`, `generate`
a `Score` from it, and `transform` or `edit` the result (see the modules)."""

from .engine import ENGINE_VERSION, generate
from .spec import BeatSpec

__all__ = ["ENGINE_VERSION", "BeatSpec", "generate"]
