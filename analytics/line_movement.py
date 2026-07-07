"""
Line movement analysis.

Compares the current line to a previously stored snapshot to detect
sharp money signals and line direction.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class LineMovement:
    player:     str
    stat:       str
    old_line:   float
    new_line:   float
    delta:      float       # new_line - old_line
    direction:  str         # "DOWN", "UP", "FLAT"
    signal:     str         # human-readable interpretation


def analyze_movement(player: str, stat: str, old_line: float, new_line: float) -> LineMovement:
    """
    Classify a line movement and return an interpretation.

    A line moving DOWN (e.g. 22.5 → 20.5) means the book expects the player
    to score less — or sharp action is fading the Over.
    A line moving UP means the book expects more output — or action is on the Over.
    """
    delta = round(new_line - old_line, 2)

    if delta < -0.4:
        direction = "DOWN"
        signal = f"Line dropped {abs(delta):.1f} — possible sharp Under action or injury concern."
    elif delta > 0.4:
        direction = "UP"
        signal = f"Line rose {delta:.1f} — heavy Over action or positive news."
    else:
        direction = "FLAT"
        signal = "Line stable — no significant movement."

    return LineMovement(
        player=player,
        stat=stat,
        old_line=old_line,
        new_line=new_line,
        delta=delta,
        direction=direction,
        signal=signal,
    )
