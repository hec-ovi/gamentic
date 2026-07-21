"""Streaming-safe view over the batch hygiene in parsing.py.

The scrubbers in parsing.py are the single source of truth and stay batch: on every
fragment the ACCUMULATED raw text is re-scrubbed whole, and only the stable prefix of
the result is released for display. Stability is conservative: nothing is released
while it could still be retro-eaten by a rule that needs more text to decide (an open
think-paren, an unclosed tag or fence, a line that still looks like it may become a
tool-call/JSON/scaffold line, end-anchored debris trims). When a rule does fire across
already-released text (rare by design), the view says so and the display REPLACES that
beat's text instead of appending - and finalize() always returns the canonical batch
result, so the stored beat is byte-identical to what the non-streaming pipeline
produces. Divergence can cost a visual correction; it can never corrupt a beat.

Cost note: re-scrubbing O(beat) per fragment is O(beat^2) per beat worst case, which
at narration sizes (a few KB) is microseconds per token against a ~55 tok/s model.
"""
import re

from . import parsing

# Junk-line shapes a line-in-progress could still grow into; while the current
# (unterminated) line matches one of these PREFIX forms, it stays unreleased.
#   - a bare identifier can still become name(...) / name {...} (_TOOL_CALL/_CODE_LINE)
#   - a run of -*_ can still become a markdown rule (_MD_RULE)
#   - short word-run + "tools"-ish can still become the bare scaffold label (_TOOLS_BARE)
#   - comment glyph openers (_COMMENT_LINE)
_UNDECIDED_LINE = (
    re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*$"),
    # a call/brace body in progress (name(...), name {json}) is a junk-line candidate
    # until its newline decides it - even with the parens already closed, a trailing
    # "# comment" may still be coming (_TOOL_CALL/_CODE_LINE judge the WHOLE line)
    re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*[({]"),
    # a line OPENING with [ or { may end as a bare JSON/bracket line (_JSON_LINE)
    re.compile(r"^\s*[\[{]"),
    # markdown furniture and fence backticks (_MD_RULE, _FENCE opener)
    re.compile(r"^\s*[-*_`\s]+$"),
    re.compile(r"^\s*[\w ]{0,12}$"),
    re.compile(r"^\s*[\w ]{0,12}tools?(?:[ _]?calls?)?\s*:?\s*$", re.I),
    re.compile(r"^\s*(?:/|\*)[/*]?\s*$"),
)
# First line only: a leading Name-colon-quote is screenplay impersonation and dies
# whole; while the first line is still a candidate for that shape, hold it.
_SCREENPLAY_CANDIDATE = re.compile(r"^[A-Z][\w .'-]{0,40}:?[\"“]?$")

# End-anchored volatility: these can be trimmed off the tail by debris rules or the
# final strip once more text arrives, so a released text never ends with them.
_VOLATILE_TAIL = " \t\n]*["


def _unclosed_cut(text: str) -> int:
    """Index where the earliest still-open construct starts (len(text) if none):
    an unmatched ( [ < or {, or the opener of an odd ``` fence. Everything from
    that point on could still be eaten whole once the construct closes."""
    cut = len(text)
    fence = 0
    for m in re.finditer(r"```", text):
        fence ^= 1
        if fence:
            cut = min(cut, m.start())
    if fence == 0:
        cut = len(text)
    for op, cl in (("(", ")"), ("[", "]"), ("<", ">"), ("{", "}")):
        depth, first_open = 0, None
        for i, ch in enumerate(text):
            if ch == op:
                depth += 1
                if first_open is None:
                    first_open = i
            elif ch == cl and depth:
                depth -= 1
                if depth == 0:
                    first_open = None
        if depth and first_open is not None:
            cut = min(cut, first_open)
    return cut


def _stable_len(clean: str, first_line_special: bool) -> int:
    """How much of a scrubbed text is safe to show, given more raw text may follow."""
    end = _unclosed_cut(clean)
    stable = clean[:end]
    # the line still being written may yet become a junk line: hold it back whole
    nl = stable.rfind("\n")
    line = stable[nl + 1:]
    if line and any(p.match(line) for p in _UNDECIDED_LINE):
        end = nl + 1 if nl >= 0 else 0
    elif first_line_special and nl < 0 and _SCREENPLAY_CANDIDATE.match(line):
        end = 0
    stable = clean[:end].rstrip(_VOLATILE_TAIL)
    return len(stable)


class ProseStream:
    """Narration prose, streamed. feed() returns display ops for the live view;
    finalize() returns the canonical (emotion, text) via the exact batch pipeline
    the turn runs on a narrator reply: clean_prose -> (trim_to_sentence when the
    generation hit its token ceiling) -> _scrub_narration."""

    def __init__(self):
        self.raw = ""
        self.shown = ""

    def feed(self, fragment: str) -> list[tuple[str, str]]:
        """-> [("append", text)] or [("replace", text)] or [] (nothing new stable)."""
        self.raw += fragment
        _, clean = parsing._scrub_narration(parsing.clean_prose(self.raw))
        stable = clean[: _stable_len(clean, first_line_special=True)]
        if stable == self.shown:
            return []
        if stable.startswith(self.shown):
            delta, self.shown = stable[len(self.shown):], stable
            return [("append", delta)]
        if self.shown.startswith(stable):
            return []                     # tail got retro-trimmed; wait for more text
        self.shown = stable               # a rule fired across shown text: correct it
        return [("replace", stable)]

    def finalize(self, length_capped: bool = False) -> tuple[str, str]:
        prose = parsing.clean_prose(self.raw)
        if prose and length_capped:
            prose = parsing.trim_to_sentence(prose)
        return parsing._scrub_narration(prose)


class CharacterStream:
    """A character reply, streamed. feed() returns the current stable VIEW:
    (done_segments, tail) where done_segments are batch-parsed (kind, text, emotion)
    triples that can no longer change, and tail is (kind, stable_text) of the segment
    still being written - text only for say/private (do lands whole at finalize, and
    an untagged reply stays unstreamed: its lead could still be reclassified once the
    first tag arrives). finalize() returns parse_character_output_with_marks(raw)."""

    def __init__(self):
        self.raw = ""

    def feed(self, fragment: str) -> tuple[list[tuple[str, str, str]], tuple[str, str] | None]:
        self.raw += fragment
        segs, _ = parsing.parse_character_output_with_marks(self.raw)
        if not segs:
            return [], None
        open_tag = self._open_tag_kind()
        if open_tag is None:              # no unclosed span: nothing is safely growing
            return segs[:-1], None
        done, (kind, text, _emo) = segs[:-1], segs[-1]
        if kind not in ("say", "private"):
            return done, (kind, "")
        # _unquote strips a WRAPPING quote pair only once the closer arrives; drop a
        # leading quote from the live view now (the near-certain canonical form)
        # instead of flashing it and retracting it when the segment closes.
        text = text.lstrip('"“')
        stable = text[: _stable_len(text, first_line_special=False)]
        return done, (kind, stable)

    def _open_tag_kind(self) -> str | None:
        """Kind of the structural span still open at the end of raw, if any - the
        same top-level walk parse_character_output does, reduced to 'is the last
        opener still unclosed'."""
        last, inside = None, False
        pos = 0
        for m in parsing._CHAR_TAG.finditer(self.raw):
            kind = m.group(1).lower()
            if inside and last is not None and parsing._CHAR_CLOSE.search(self.raw[pos:m.start()]):
                inside = False
            if kind in ("whisper", "private") and inside:
                continue
            last, pos, inside = kind, m.end(), True
        if last is None or not inside:
            return None
        if last == "whisper":
            last = "private"             # legacy span alias, same normalization as the parser
        return None if parsing._CHAR_CLOSE.search(self.raw[pos:]) else last

    def finalize(self):
        return parsing.parse_character_output_with_marks(self.raw)
