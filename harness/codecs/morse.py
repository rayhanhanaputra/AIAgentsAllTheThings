"""International Morse code, and a blink timeline for evidence.

Used by the morse-blink encoder to render an instruction as relay/LED blinks, and by
the RelayBot target to decode what its optical/acoustic sensor observed.
"""
from __future__ import annotations

_TABLE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}
_INVERSE = {code: letter for letter, code in _TABLE.items()}


def encode_text(text: str) -> str:
    """Render text as a Morse string: letters space-separated, words joined by ' / '."""
    words = []
    for word in text.upper().split():
        words.append(" ".join(_TABLE[c] for c in word if c in _TABLE))
    return " / ".join(w for w in words if w)


def decode(morse: str) -> str:
    """Decode a Morse string back to text."""
    out = []
    for word in morse.split(" / "):
        letters = [_INVERSE.get(sym, "?") for sym in word.split() if sym]
        out.append("".join(letters))
    return " ".join(out).strip()


def to_blink(morse: str) -> list[list]:
    """A coarse on/off blink timeline (state, units) for evidence and realism."""
    seq: list[list] = []
    for ch in morse:
        if ch == ".":
            seq.append(["on", 1])
        elif ch == "-":
            seq.append(["on", 3])
        elif ch == " ":
            seq.append(["off", 3])
        elif ch == "/":
            seq.append(["off", 7])
    return seq
