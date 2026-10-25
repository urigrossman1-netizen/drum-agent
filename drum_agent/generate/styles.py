"""Groove styles for the beat generator.

A style is a set of drumming conventions, not a fixed pattern: where the backbeat
falls, what the kick leans on, how the cymbal hand moves, which syncopations are
idiomatic, how fills are phrased, and what a chorus changes. The engine
(`engine.py`) turns these conventions, the requested difficulty and complexity and
a seed into concrete strokes, so two seeds of one style are two different beats in
the same idiom.

Steps are named by metric level within a beat: "1" the beat, "&" the 8th offbeat,
"e" and "a" the 16ths around it; with a triplet feel "trip" (the middle triplet)
and "let" (the last, the swung offbeat).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Style:
    key: str
    label: str
    bpm: int
    time_signature: str = "4/4"
    triplet: bool = False  # beats divide in three (shuffle, swing) in simple meters
    cymbal: str = "hihat"  # hihat | ride
    hat_rate: str = "8ths"  # quarters | 8ths | 16ths | shuffle | triplets | jazz_ride
    open_hats: float = 0.0  # chance of an open hi-hat on the last offbeat of a phrase bar
    disco_hats: bool = False  # open hi-hat on every offbeat
    backbeat: str = "2&4"  # 2&4 | 3 (half time) | all | none | one_drop
    kick_core: str = "1"  # 1 | 1&3 | four | none
    kick_offbeats: float = 0.35  # how much the kick uses 8th offbeats (scaled by complexity)
    kick_16ths: float = 0.0  # how much it uses the 16ths around the beat
    kick_favorites: tuple[str, ...] = ()  # (beat:level) slots this style leans on, e.g. "3&" = and of 3
    double_bass: bool = False
    ghosts: float = 0.0  # snare ghost-note density at full complexity
    snare_inst: str = "snare"
    pedal_hat: str = "none"  # none | 2&4 | beats | offbeats
    fill_rate: int = 4  # strokes per beat in fills: 2, 3, 4 or 6
    fill_voices: tuple[str, ...] = ("snare", "tom1", "tom2", "floor_tom")
    chorus: str = "crash_quarters"  # what a high-energy section changes: ride | crash_quarters | open_hats | busier
    breakdown: str = "half_time"  # half_time | floor_tom | sparse
    energy: str = "medium"  # low | medium | high (velocities)
    phrase: int = 4  # bars per phrase
    words: tuple[str, ...] = field(default_factory=tuple)  # prompt words that select this style


STYLES: dict[str, Style] = {s.key: s for s in [
    Style("rock", "Rock", 110, kick_core="1&3", kick_offbeats=0.45, kick_favorites=("3&", "2&", "4a"),
          open_hats=0.25, ghosts=0.15, chorus="crash_quarters", words=("rock", "classic rock", "indie")),
    Style("hard_rock", "Heavy Rock", 120, kick_core="1&3", kick_offbeats=0.55, kick_16ths=0.25,
          kick_favorites=("1&", "3&", "2a", "4a"), open_hats=0.45, ghosts=0.0, chorus="crash_quarters",
          energy="high", words=("heavy rock", "hard rock", "stadium rock", "grunge", "arena rock")),
    Style("pop", "Pop", 104, kick_core="1&3", kick_offbeats=0.4, kick_16ths=0.15, kick_favorites=("2&", "3&"),
          open_hats=0.2, ghosts=0.2, chorus="open_hats", words=("pop", "dance pop", "synth pop")),
    Style("pop_punk", "Pop-Punk", 170, kick_core="1&3", kick_offbeats=0.5, kick_favorites=("2&", "3&", "4&"),
          open_hats=0.1, ghosts=0.0, fill_rate=4, chorus="crash_quarters", energy="high", phrase=4,
          words=("pop-punk", "pop punk", "pop‑punk", "emo", "skate punk", "easycore")),
    Style("punk", "Punk", 180, hat_rate="8ths", kick_core="1&3", kick_offbeats=0.5, kick_favorites=("2&", "4&"),
          chorus="crash_quarters", energy="high", words=("punk", "hardcore punk", "garage")),
    Style("metal", "Metal", 150, kick_core="1&3", kick_offbeats=0.6, kick_16ths=0.4, double_bass=True,
          kick_favorites=("1e", "1&", "3e", "3&"), chorus="crash_quarters", fill_rate=6, energy="high",
          fill_voices=("snare", "tom1", "tom2", "floor_tom", "floor_tom2"),
          words=("metal", "thrash", "double bass", "double kick", "double-kick", "metalcore", "djent")),
    Style("funk", "Funk", 96, hat_rate="16ths", kick_core="1", kick_offbeats=0.4, kick_16ths=0.55,
          kick_favorites=("1a", "2&", "3&", "3a", "4e"), open_hats=0.35, ghosts=0.55, chorus="busier",
          words=("funk", "funky", "james brown", "slap")),
    Style("rnb", "R&B", 82, hat_rate="16ths", kick_core="1", kick_offbeats=0.35, kick_16ths=0.3,
          kick_favorites=("1a", "2&", "3&", "3a"), open_hats=0.3, ghosts=0.35, snare_inst="snare",
          chorus="busier", energy="low", fill_rate=4,
          words=("r&b", "rnb", "r and b", "neo soul", "neo-soul", "soul", "slow jam")),
    Style("hip_hop", "Hip-Hop", 90, hat_rate="8ths", kick_core="1", kick_offbeats=0.45, kick_16ths=0.4,
          kick_favorites=("1&", "2a", "3&", "3a"), open_hats=0.25, ghosts=0.25, chorus="busier",
          words=("hip-hop", "hip hop", "hiphop", "boom bap", "boom-bap", "rap", "lo-fi", "lofi")),
    Style("half_time", "Half-Time", 140, hat_rate="8ths", backbeat="3", kick_core="1", kick_offbeats=0.4,
          kick_16ths=0.3, kick_favorites=("1&", "2a", "4&"), open_hats=0.3, ghosts=0.3, chorus="ride",
          words=("half-time", "half time", "halftime")),
    Style("shuffle", "Shuffle", 116, triplet=True, hat_rate="shuffle", kick_core="1&3", kick_offbeats=0.35,
          kick_favorites=("2let", "4let"), ghosts=0.3, fill_rate=3, chorus="ride",
          words=("shuffle", "blues", "swing rock", "boogie", "texas")),
    Style("jazz", "Jazz Swing", 140, triplet=True, cymbal="ride", hat_rate="jazz_ride", backbeat="none",
          kick_core="none", kick_offbeats=0.25, pedal_hat="2&4", ghosts=0.35, fill_rate=3, chorus="busier",
          energy="low", breakdown="sparse", words=("jazz", "swing", "bebop", "big band")),
    Style("reggae", "Reggae One Drop", 76, triplet=False, hat_rate="8ths", backbeat="one_drop",
          kick_core="none", kick_offbeats=0.0, snare_inst="cross_stick", open_hats=0.2, fill_rate=4,
          chorus="busier", energy="low", words=("reggae", "one drop", "one-drop", "dub", "roots")),
    Style("disco", "Four on the Floor", 120, hat_rate="8ths", disco_hats=True, kick_core="four",
          kick_offbeats=0.0, ghosts=0.0, chorus="busier", open_hats=0.0,
          words=("disco", "four on the floor", "four-on-the-floor", "house", "edm", "dance", "techno", "electro")),
    Style("ballad", "Ballad", 72, hat_rate="8ths", kick_core="1&3", kick_offbeats=0.25, snare_inst="cross_stick",
          ghosts=0.0, chorus="ride", energy="low", fill_rate=4, words=("ballad", "slow", "power ballad")),
    Style("country", "Country Train Beat", 140, hat_rate="8ths", kick_core="1&3", kick_offbeats=0.15,
          ghosts=0.4, chorus="crash_quarters", words=("country", "train beat", "bluegrass", "two-step")),
    Style("bossa", "Bossa Nova", 130, hat_rate="8ths", cymbal="ride", backbeat="none", kick_core="none",
          snare_inst="cross_stick", chorus="busier", energy="low", fill_rate=4,
          words=("bossa", "bossa nova", "latin", "samba")),
    Style("six_eight", "6/8 Groove", 66, time_signature="6/8", hat_rate="8ths", kick_core="1", kick_offbeats=0.3,
          ghosts=0.1, fill_rate=3, chorus="ride", energy="low", words=("6/8", "six-eight", "six eight")),
    Style("waltz", "Waltz", 150, time_signature="3/4", hat_rate="8ths", backbeat="2&3", kick_core="1",
          kick_offbeats=0.2, chorus="ride", energy="low", words=("waltz", "3/4 time")),
]}

DEFAULT_STYLE = "rock"
