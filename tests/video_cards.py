"""Parse the Remotion source into the cards it renders, and the text on each.

WHY THIS EXISTS
---------------
A rendered frame is the artifact, and a guard that greps the whole source file
cannot tell the difference between a clause on the card that needs it and the
same clause eleven scenes later. Both satisfy "the file contains it"; only one
is read by someone who watches thirty seconds.

`README.md` already gets per-document treatment from
`tests/test_claims_uncompressed.py`. This gives the video the same thing at the
granularity that matters for a video, which is the CARD -- the unit a viewer
sees whole and alone.

WALKS WHAT EXISTS
-----------------
`cards()` discovers scenes by finding every `const X: React.FC` in the source
and every entry in the `SCENES` array, and `test_video_cards.py` asserts the two
agree. A guard that enumerates a fixed subset of what it protects protects only
what it happened to list (CLAUDE.md, the seventh instance): a new scene must
either be covered or make this fail, and it cannot be quietly skipped.

WHAT COUNTS AS DISPLAYED TEXT
-----------------------------
Every string literal in the scene body, with `${...}` interpolations replaced by
a placeholder. That over-collects a little -- flexbox keywords like `"column"`
come along -- which is safe for both consumers here: the compression guard looks
for prose clauses, and the no-literals guard reports digits, and layout keywords
contain neither.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "video" / "src" / "Recoup.tsx"

#: Stands in for an interpolated expression. Chosen so it contains no digits and
#: no prose -- it must not accidentally satisfy either guard that reads it.
INTERPOLATION = "\x00"

_SCENE = re.compile(r"^const (\w+): React\.FC = \(\) => \(", re.MULTILINE)
_SCENES_ARRAY = re.compile(r"\[(\w+), secs\(")
_STRING = re.compile(
    r'"((?:[^"\\\n]|\\.)*)"' r"|'((?:[^'\\\n]|\\.)*)'" r"|`((?:[^`\\]|\\.)*)`",
    re.DOTALL,
)
_INTERP = re.compile(r"\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_JSX_COMMENT = re.compile(r"\{\s*/\*.*?\*/\s*\}", re.DOTALL)


@dataclass
class Card:
    """One scene, and the text it puts on screen."""

    name: str
    body: str
    strings: list[str] = field(default_factory=list)
    interpolations: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.strings)


def _strip_comments(text: str) -> str:
    """Comments are not displayed, and they discuss the very claims these guards
    look for -- the A-029 note beside the MDE stat names both figures. A guard
    reading them would pass on an explanation of the rule instead of on the text
    that obeys it.
    """
    text = _JSX_COMMENT.sub("", text)
    text = _BLOCK_COMMENT.sub("", text)
    return _LINE_COMMENT.sub("", text)


def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def declared_scene_order() -> list[str]:
    """The scenes the SCENES array actually renders, in order."""
    body = source()
    start = body.index("const SCENES")
    return _SCENES_ARRAY.findall(body[start:])


def cards(text: str | None = None) -> list[Card]:
    """Every `React.FC` scene in the source, with its displayed strings."""
    body = text if text is not None else source()
    found: list[Card] = []
    marks = list(_SCENE.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        raw = _strip_comments(body[m.end() : end])
        card = Card(name=m.group(1), body=raw)
        for match in _STRING.finditer(raw):
            literal = next(g for g in match.groups() if g is not None)
            card.interpolations.extend(_INTERP.findall(literal))
            card.strings.append(_INTERP.sub(INTERPOLATION, literal))
        found.append(card)
    return found
