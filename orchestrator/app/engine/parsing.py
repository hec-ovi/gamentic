"""Text hygiene + character-output parsing: everything that turns raw model text into
clean, displayable beats (scrubbed prose, tagged say/do segments, emotion extraction)."""
import re

from .. import tools

_CHAR_TAG = re.compile(r"\[(say|do)\]", re.I)
_CHAR_CLOSE = re.compile(r"\[/?(?:say|do)\]", re.I)
# Hygiene for small-model artifacts seen live: a pseudo tool call leaked as text
# ("[attack{amount:10,target: \"player\"}]") and stray tag debris ("*]", trailing "*").
_PSEUDO_TOOL = re.compile(r"\[\w+\s*\{[^\[\]]*\}\s*\]?")
_TAG_DEBRIS = re.compile(r"(\*+\]|\[+\*+|[\[\]*]+$)")
# Tool-call shapes leaked AS PROSE (live: the model occasionally printed call syntax like
# move_location("the docks") instead of calling the tool). Any line carrying a known tool
# name followed by ( or { is junk, as is a bare JSON-object line or a fenced code block.
_TOOL_NAMES = sorted({t["function"]["name"] for t in tools.NARRATOR_TOOLS + tools.CHARACTER_TOOLS}
                     | {"reject_attempt", "submit_segments", "save_world"})
_TOOL_CALL = re.compile(r"\b(?:%s)\s*[({]" % "|".join(_TOOL_NAMES))
_JSON_LINE = re.compile(r"^\s*[\[{].*[\]}]\s*,?\s*$")
_FENCE = re.compile(r"```.*?(?:```|$)", re.S)


def trim_to_sentence(text: str) -> str:
    """A generation that hit the token ceiling ends mid-word (live: 'we do not linger
    for <'); cut back to the last completed sentence so truncation is never visible."""
    cut = max(text.rfind(p) for p in (". ", "! ", "? ", ".\n", "!\n", "?\n"))
    last = max(text.rfind(p) for p in (".", "!", "?", "…"))
    if last == len(text) - 1:
        return text                      # already ends cleanly
    return text[: cut + 1].rstrip() if cut > 0 else text


def clean_prose(text: str) -> str:
    """Scrub model leakage from prose shown to the player: fenced code blocks, bare JSON
    lines, lines written in tool-call syntax, and inline pseudo tool calls."""
    text = _FENCE.sub("", text or "")
    lines = [ln for ln in text.splitlines()
             if not _TOOL_CALL.search(ln) and not _JSON_LINE.match(ln)]
    text = _PSEUDO_TOOL.sub("", "\n".join(lines))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _clean_segment(text: str) -> str:
    text = _PSEUDO_TOOL.sub("", text)
    text = "\n".join(ln for ln in text.splitlines() if not _TOOL_CALL.search(ln))
    text = _TAG_DEBRIS.sub("", text)
    return text.strip()


def _unquote(text: str) -> str:
    """Strip WRAPPING quotation marks from a speech segment: the model writes
    [say]"Far enough."[/say], but a dialogue bubble supplies its own framing, so the
    quotes read as artifacts on screen. Partial/inner quotes are left alone."""
    if len(text) >= 2 and text[0] in '"“' and text[-1] in '"”':
        return text[1:-1].strip()
    return text


# Emotion vocabulary: accepted word -> what the voice-api can actually render ('' = no
# tone). The model writes the wider set; calm/nervous/tired/etc. were silently dropped
# voice-side, so the mapping happens HERE and beat.emotion only ever carries renderable
# tones. All 20 words stay accepted for display-scrubbing. A speech segment may OPEN
# with one tag ([whisper] or the Maya1-habit <whisper>); it becomes the beat's base tone
# and is stripped from the display text. Unknown leading tags are scrubbed as artifacts.
EMOTIONS = {e: e for e in ("laugh", "giggle", "chuckle", "sigh", "whisper", "angry",
                           "gasp", "cry", "scream", "excited", "sad")}
EMOTIONS.update({"shout": "scream", "yell": "scream", "sob": "cry", "happy": "excited",
                 "scared": "gasp", "furious": "angry", "tired": "sigh",
                 "nervous": "gasp", "calm": ""})
_EMOTION_TAG = re.compile(r"^[\[<](\w+)[\]>]\s*")
_ANY_TAG = re.compile(r"\[\w+\]\s*")
# Stray angle-bracket tags scrub by EMOTION WORD only (opening or closing form): unlike
# square tags, angle brackets carry legitimate text the model may write.
_ANGLE_TAG = re.compile(r"</?(?:%s)>\s*" % "|".join(EMOTIONS), re.I)


def _extract_emotion(text: str) -> tuple[str, str]:
    """(emotion, clean_text): a leading known [tag] or <tag> becomes the line's tone
    (mapped to its renderable value); remaining bracketed single-word tags and angle
    emotion tags anywhere are scrubbed so they never show on screen."""
    emotion, found = "", False
    m = _EMOTION_TAG.match(text)
    while m and m.group(1).lower() in EMOTIONS:
        if not found:   # first tag wins; extras are scrubbed
            emotion, found = EMOTIONS[m.group(1).lower()], True
        text = text[m.end():]
        m = _EMOTION_TAG.match(text)
    return emotion, _ANGLE_TAG.sub("", _ANY_TAG.sub("", text)).strip()


# Narrator prose: emotion tags leak in BOTH forms and were shown verbatim AND honored by
# TTS (live: inline [whisper] on screen). Scrub touches only known emotion words (plus
# the model's [pause] filler) because prose may carry legitimate bracketed text;
# clean_prose stays generic (it also cleans summaries).
_PROSE_TAG = re.compile(r"[\[<]/?(?:%s|pause)[\]>]\s*" % "|".join(EMOTIONS), re.I)


def _scrub_narration(text: str) -> tuple[str, str]:
    """(emotion, clean_text) for narration prose: a leading known tag is lifted as the
    beat's tone (mapped to its renderable value); every emotion tag is scrubbed."""
    emotion = ""
    m = _EMOTION_TAG.match(text or "")
    if m and m.group(1).lower() in EMOTIONS:
        emotion = EMOTIONS[m.group(1).lower()]
    return emotion, _PROSE_TAG.sub("", text or "").strip()


def _reclassify_do(content: str) -> tuple[str, str, str]:
    """A 'do' segment that is emotion tags + a fully quoted span IS speech the model
    mis-tagged (live: [do][sigh] [whisper] "Do not waste your breath..."[/do] rendered
    as an italic action, tags visible, never voiced). Judged by SHAPE, not wording."""
    emotion, cleaned = _extract_emotion(content)
    if len(cleaned) >= 2 and cleaned[0] in '"“' and cleaned[-1] in '"”':
        return "say", _unquote(cleaned), emotion
    return "do", cleaned, ""   # genuine action: tags scrubbed, no tone (actions aren't spoken)


def parse_character_output(text: str) -> list[tuple[str, str, str]]:
    """Split a character's tagged reply into (kind, content, emotion) where kind is
    'say' or 'do'. [say]...[/say] -> speech (dialogue beat); [do]...[/do] -> action.
    A speech segment may OPEN with a Maya1 emotion tag ([angry] You dare?), extracted
    into the beat's tone for the voice and stripped from the display text.
    Tolerant: untagged text is treated as speech; text before the first tag as action."""
    text = (text or "").strip()
    if not text:
        return []
    matches = list(_CHAR_TAG.finditer(text))
    if not matches:
        emotion, cleaned = _extract_emotion(_unquote(_clean_segment(text)))
        return [("say", cleaned, emotion)] if cleaned else []
    segs: list[tuple[str, str, str]] = []
    lead = _clean_segment(text[: matches[0].start()])
    if lead:
        segs.append(_reclassify_do(lead))
    for i, m in enumerate(matches):
        kind = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = _clean_segment(_CHAR_CLOSE.sub("", text[start:end]))
        emotion = ""
        if kind == "say":
            # the tag may sit inside or outside the quotes: unquote, extract, unquote
            content = _unquote(content)
            emotion, content = _extract_emotion(content)
            content = _unquote(content)
            # the model sometimes writes stage directions as a leading (parenthetical)
            # inside the speech (live: '(She looks at the stone...) "A whetstone..."');
            # those are ACTIONS: split them into their own do beat so they are never
            # spoken aloud or shown inside a speech bubble
            while content.startswith("(") and ")" in content:
                inner, _, rest = content[1:].partition(")")
                if inner.strip():
                    segs.append(("do", inner.strip(), ""))
                content = _unquote(rest.strip())
        elif kind == "do":
            kind, content, emotion = _reclassify_do(content)
        if content:
            segs.append((kind, content, emotion))
    return segs
