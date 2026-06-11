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
# move_location("the docks") instead of calling the tool). Only a FULL-LINE call shape is
# junk - name(args) or name {json-ish} with nothing else on the line - as is a bare
# JSON-object line or a fenced code block. The old 'name followed by ( or {' substring
# rule deleted legitimate lines whole (static review 2026-06-11: 'We attack (quietly) at
# dawn' silenced a character because attack is a tool name).
_TOOL_NAMES = sorted({t["function"]["name"] for t in tools.NARRATOR_TOOLS + tools.CHARACTER_TOOLS}
                     | {"reject_attempt", "submit_segments", "save_world"})
_TOOL_CALL = re.compile(r"^\s*(?:%s)(?:\([^()]*\)|\s*\{[^{}]*\})\s*(?:#.*)?$" % "|".join(_TOOL_NAMES))
_JSON_LINE = re.compile(r"^\s*[\[{].*[\]}]\s*,?\s*$")
# A separator-only line ("---", "***"): markdown furniture, never prose. Left alone it
# can BE the whole narration beat (live showcase 2026-06-11: a turn's narration was the
# literal string "---", which counted as prose and kept the resolve pass from firing).
_MD_RULE = re.compile(r"^\s*[-*_]{3,}\s*$")
_FENCE = re.compile(r"```.*?(?:```|$)", re.S)


def trim_to_sentence(text: str) -> str:
    """A generation that hit the token ceiling ends mid-word (live: 'we do not linger
    for <'); cut back to the last completed sentence so truncation is never visible.
    A cut text with NO completed sentence returns empty (live: 'from the sheer shock
    of the lig' displayed verbatim) - the callers drop empty fragments."""
    cut = max(text.rfind(p) for p in (". ", "! ", "? ", ".\n", "!\n", "?\n"))
    last = max(text.rfind(p) for p in (".", "!", "?", "…"))
    if last == len(text) - 1:
        return text                      # already ends cleanly
    return text[: cut + 1].rstrip() if cut > 0 else ""


# A line that is NOTHING BUT a bare call expression (plus an optional trailing comment)
# is junk regardless of the name (live: a HALLUCINATED 'set_distance(distance="close")
# # Implicit in the tense standoff.' leaked as prose; _TOOL_CALL only knows real tool
# names). Anchored to the whole line, so prose with mid-sentence parens survives.
_CODE_LINE = re.compile(r"^\s*[a-z_][a-z0-9_]*\(.*\)\s*(?:#.*)?$", re.I)


def clean_prose(text: str) -> str:
    """Scrub model leakage from prose shown to the player: fenced code blocks, bare JSON
    lines, lines written in tool-call syntax, and inline pseudo tool calls."""
    text = _FENCE.sub("", text or "")
    lines = [ln for ln in text.splitlines()
             if not _TOOL_CALL.match(ln) and not _JSON_LINE.match(ln)
             and not _CODE_LINE.match(ln) and not _MD_RULE.match(ln)]
    text = _PSEUDO_TOOL.sub("", "\n".join(lines))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# A closing square tag is NEVER meaningful display text (live: '[/whisper]' shipped to
# screen as '[/whisper' because the trailing-debris scrub ate its bracket first). It
# must die WHOLE, before _TAG_DEBRIS can unbalance it.
_CLOSE_TAG = re.compile(r"\[/\w+\]\s*")


# Character-path brace lines only: square-bracket lines are the say/do/emotion
# vocabulary itself and must survive (_JSON_LINE would eat '[say]...[/say]' whole).
_BRACE_LINE = re.compile(r"^\s*\{.*\}\s*,?\s*$")


# Comment furniture and half-written calls (live 2026-06-11, the same reply that
# proved the memory tools: the dialogue ended "...stone now.\n*/\n[admit_trait" - the
# model both CALLED admit_trait for real and started writing it as text before the
# parser cut it). A line of pure comment glyphs dies; a trailing unclosed [word
# fragment at the very end of a segment dies with it.
_COMMENT_LINE = re.compile(r"^\s*(?:/\*|\*/|//+)\s*$")
_DANGLING_CALL = re.compile(r"\n?\s*\[[a-z_]+\s*$", re.I)


def _clean_segment(text: str) -> str:
    text = strip_markup(text)
    text = _PSEUDO_TOOL.sub("", text)
    text = "\n".join(ln for ln in text.splitlines()
                     if not _TOOL_CALL.match(ln) and not _BRACE_LINE.match(ln)
                     and not _COMMENT_LINE.match(ln))
    text = _DANGLING_CALL.sub("", text)
    text = _CLOSE_TAG.sub("", text)
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
_ANY_TAG = re.compile(r"\[/?\w+\]\s*")
# Stray angle-bracket tags scrub by EMOTION WORD only (opening or closing form): unlike
# square tags, angle brackets carry legitimate text the model may write.
_ANGLE_TAG = re.compile(r"</?(?:%s)>\s*" % "|".join(EMOTIONS), re.I)

# Markup guard (live, e2e 2026-06-11 turn 19: the narrator emitted a raw '<div style=...>'
# state panel, '<strong>Exits:</strong>' lists and all, INTO A STORED NARRATION BEAT; no
# sanitizer knew markup). HTML is never legitimate prose. A line that OPENS with a tag is
# structure and dies whole, so a panel like that one reduces to nothing; a tag inside a
# prose line loses only the tag. Known angle words are exempt: <whisper>/<pause> belong
# to the emotion/filler scrubs, and <think> must reach the think-strip INTACT so the
# reasoning dies WITH its tags instead of being unwrapped into visible prose.
_HTML_TAG = re.compile(r"</?(?!(?:think|pause|%s)\b)[a-zA-Z][^>]*>" % "|".join(EMOTIONS),
                       re.I)


def strip_markup(text: str) -> str:
    out = []
    for ln in (text or "").splitlines():
        if _HTML_TAG.match(ln.lstrip()):   # structural line: junk whole
            continue
        out.append(re.sub(r" {2,}", " ", _HTML_TAG.sub("", ln)).rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


def _strip_bracket_debris(text: str) -> str:
    """Unbalanced bracket remnants of half-formed tag markup survive every tag-shaped
    scrub (live, e2e 2026-06-11 edge-C: a dialogue beat stored as 'The keeper?!]' after
    the leading [angry] was lifted, leaving a stray close-bracket no rule recognized).
    Only the SURPLUS side dies: balanced brackets are legitimate speech."""
    while text.endswith("]") and text.count("]") > text.count("["):
        text = text[:-1].rstrip()
    while text.startswith("[") and text.count("[") > text.count("]"):
        text = text[1:].lstrip()
    return text


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
    return emotion, _strip_bracket_debris(
        _ANGLE_TAG.sub("", _ANY_TAG.sub("", text)).strip())


# Narrator prose: emotion tags leak in BOTH forms and were shown verbatim AND honored by
# TTS (live: inline [whisper] on screen). Scrub touches only known emotion words (plus
# the model's [pause] filler) because prose may carry legitimate bracketed text;
# clean_prose stays generic (it also cleans summaries).
_PROSE_TAG = re.compile(r"[\[<]/?(?:%s|pause)[\]>]\s*" % "|".join(EMOTIONS), re.I)


# The model prints the worked example's reasoning aloud (live: 12 of 20 narration beats
# opened with "(think: ...)"; later, turn 53 carried a multi-line think with a NESTED
# parenthetical inside, plus a mid-line opener). The span is stripped wherever it starts,
# parens balanced across lines; a think that never closes is reasoning to the end of the
# text and takes it along. The XML habit ('<think>...</think>', unclosed = to the end of
# the text) dies the same way, and BEFORE the markup guard could eat just its tags and
# leave the reasoning standing as prose. Was narration-only by design; the 2026-06-11
# audit proved character replies, folds and /explain leak the same artifacts, so every
# model-text path strips now (strip_reasoning below).
_THINK_OPEN = re.compile(r"\(\s*think\b", re.I)
_XML_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.I | re.S)


def _strip_think(text: str) -> str:
    text = _XML_THINK.sub("", text)
    out, i = [], 0
    while True:
        m = _THINK_OPEN.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        depth, j = 0, m.start()
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= len(text):     # never closed: everything after is reasoning
            break
        i = j + 1
    cleaned = "".join(out)
    lines = [re.sub(r" {2,}", " ", ln).strip() for ln in cleaned.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


# The model sometimes writes the worked example's SHAPE as text instead of calling
# tools (live, turn 53: a "tools: { set_scene_status: ... }" object block and a
# "Prose:" label, none of it real calls). The block dies whole, braces balanced
# across lines; the label is lifted and its line's content kept.
_TOOLS_OPEN = re.compile(r"^\s*\w*tools?\s*:\s*\{", re.I)
_PROSE_LABEL = re.compile(r"^\s*prose\s*:\s*", re.I)
# A BARE tool-ish label line ("tools:", "call_tools:", "Tool calls:") with nothing after
# it: the model announcing calls it never writes (live showcase 2026-06-11: a beautiful
# narration ended in a stranded "call_tools:" line - the snake_case variant dodged both
# the "\ntools:" stop and the brace-opened block rule above).
_TOOLS_BARE = re.compile(r"^\s*[\w ]{0,12}tools?(?:[ _]?calls?)?\s*:\s*$", re.I)


def _strip_scaffold(text: str) -> str:
    out, depth = [], 0
    for ln in text.splitlines():
        if depth == 0 and _TOOLS_OPEN.match(ln):
            depth = max(0, ln.count("{") - ln.count("}"))
            continue
        if depth > 0:
            depth = max(0, depth + ln.count("{") - ln.count("}"))
            continue
        if _TOOLS_BARE.match(ln):
            continue
        out.append(_PROSE_LABEL.sub("", ln))
    return "\n".join(out)


def strip_reasoning(text: str) -> str:
    """Both think habits plus the example scaffold, one pass. Every path that turns
    model text into stored or displayed words runs this; the 2026-06-11 audit caught
    each path that skipped it (character replies, folds, /explain) leaking."""
    return _strip_scaffold(_strip_think(text or ""))


def scrub_model_text(text: str) -> str:
    """The full hygiene pass for model text that leaves the turn pipeline (fold
    memories, /explain answers): clean_prose plus the think/scaffold/markup strip.
    Folds matter most: a stored recap is re-fed to prompts EVERY turn, so one leaked
    scaffold compounds (e2e 2026-06-11: the turn-53 bytes passed clean_prose whole)."""
    return strip_markup(strip_reasoning(clean_prose(text))).strip()


# A screenplay impersonation in the FIRST line dodges the stop list: every name-colon
# stop begins with '\n' (turn.py builds them), so a reply OPENING with 'Vane: "Movement.
# Now."' sails through and no scrub caught it (live, e2e 2026-06-11). No cast list is
# available here, so the shape is judged generically: a leading Name-colon followed
# immediately by an opening quote is faked dialogue and that line dies. Prose with a
# mid-sentence colon has no quote right after it and survives.
_SCREENPLAY = re.compile(r"^[A-Z][\w .'-]{0,40}:\s*[\"“]")


def _scrub_narration(text: str) -> tuple[str, str]:
    """(emotion, clean_text) for narration prose: think-spans and example-scaffold
    blocks are stripped first, then leaked markup, then a first-line screenplay
    impersonation; a leading known tag is lifted as the beat's tone (mapped to its
    renderable value); every emotion tag is scrubbed."""
    text = strip_markup(strip_reasoning(text or "")).strip()
    first, _, rest = text.partition("\n")
    if _SCREENPLAY.match(first):
        text = rest.strip()
    emotion = ""
    m = _EMOTION_TAG.match(text)
    if m and m.group(1).lower() in EMOTIONS:
        emotion = EMOTIONS[m.group(1).lower()]
    return emotion, _PROSE_TAG.sub("", text).strip()


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
    Tolerant: untagged text is treated as speech; text before the first tag as action.
    Think spans and scaffold are stripped BEFORE any tag parsing (live, e2e 2026-06-11:
    a leading '(think: ...)' fell into the parenthetical splitter below and shipped as
    a player-visible do beat): reasoning is deleted, never reclassified."""
    text = strip_reasoning(text).strip()
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

# The character's memory marks, written as text. Live (2026-06-11, first night of the
# self-memory tools): the 26B character agents narrate their tool use instead of
# emitting calls - a whispered life story arrived with {piece: "..."} and {trait:
# "haunted by silence"} printed INSIDE a [do] block, and no real calls at all. Same
# lesson as the say/do tags themselves: parse the intent, never demand the protocol.
# Both channels work - a real tool call and a brace-mark in prose land identically.
_MEMORY_MARK = re.compile(
    r"\{\s*(piece|trait|event)\s*:\s*\"?([^\"{}]+?)\"?\s*\}", re.I)
_MEMORY_TOOL = {"piece": "share_past", "trait": "admit_trait", "event": "mark_moment"}


def extract_memory_marks(text: str) -> tuple[str, list[tuple[str, dict]]]:
    """(clean_text, [(tool_name, args), ...]): lift every brace-mark out of a character
    segment and hand back the matching self-tool applications. The marks never reach
    the display text."""
    marks: list[tuple[str, dict]] = []

    def _take(m):
        key, value = m.group(1).lower(), m.group(2).strip()
        if value:
            arg = {"share_past": "piece", "admit_trait": "trait", "mark_moment": "event"}
            tool = _MEMORY_TOOL[key]
            marks.append((tool, {arg[tool]: value}))
        return ""
    cleaned = _MEMORY_MARK.sub(_take, text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip(), marks

def parse_character_output_with_marks(text: str):
    """(segments, memory_marks): the marks are lifted from the RAW reply first - they
    can sit anywhere, including as full brace-lines that the segment cleaner would
    otherwise eat - then the remainder parses exactly as before."""
    cleaned, marks = extract_memory_marks(text or "")
    return parse_character_output(cleaned), marks

