"""Image prompt composition: the pure layer that turns game state into FLUX prompts.
No DB writes, no media HTTP. The model's appearance text is the source, but two failure
modes are netted deterministically here: gender drift (a "woman" rendered ambiguous
because the appearance never says so) and rendered text (FLUX draws any words it finds
an excuse for: sign names, lettering, watermarks)."""
import re

from .. import repo, llm, prompts


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "img"


_QUOTED = re.compile(r'["“”][^"“”]*["“”]')   # "..." spans (incl. curly quotes)
# standalone '...' spans (a ship name like 'Star-Strider') but never apostrophes in words
_SQUOTED = re.compile(r"(?<!\w)'[^'\n]{1,80}'(?!\w)")


def _strip_quoted(s: str) -> str:
    return _SQUOTED.sub("", _QUOTED.sub("", s or "")).strip()


def _place_text(sc) -> str:
    """The art subject for a scene: its NAME (the concrete place) leading its description,
    quoted spans stripped. Description alone can be world-level prose; the name anchors it."""
    desc = _strip_quoted(sc["description"])
    name = (sc["name"] or "").strip()
    if not desc:
        return name
    if name and name.lower() not in desc.lower():
        return f"{name}. {desc}"
    return desc
# FLUX has no negative prompt and negation phrasing backfires ("no text" invites text);
# per the official BFL prompting guide, exclusions are phrased as the positive visual
# that occupies the space. https://docs.bfl.ai/guides/prompting_guide_t2i_negative
NO_TEXT_GUARD = "plain unmarked surfaces, no signage"


def _gendered_base(c) -> str:
    """A character's visual base: appearance text with an explicit gender lead from the
    character's STORED gender (decided once at creation), so the portrait can never
    disagree with the narrator's pronouns. The net (repo.gender_hint) only remains as
    the fallback inside repo.character_gender for legacy rows."""
    base = (c["appearance"] or c["description"] or c["persona"] or c["name"]).strip()
    gender = repo.character_gender(c)
    if gender and not repo.gender_hint(base):
        base = f"{gender}, {base}"
    return base


def character_descriptor(c) -> str:
    """The outgoing image descriptor: explicit gender first, then looks, then the no-text guard."""
    return f"{_gendered_base(c)}, {NO_TEXT_GUARD}"


def scene_prompt(sc, style: str) -> str:
    """Scene art prompt: the place (name + description, quoted spans stripped since sign
    and ship names provoke garbled rendered text), the world style, the no-text guard."""
    return ", ".join(x for x in [_place_text(sc), style, NO_TEXT_GUARD] if x)


# ---------- the 'See' snapshot (scene + present characters, grounded in state) ----------
# Built to the FLUX.2 klein recipe (official BFL prompting guide): subjects first, ONE
# positionally anchored sentence per character so traits don't bleed, at most 3 people
# (the 4B blending ceiling), style named once for the whole frame, exclusions phrased
# positively, total kept tight (klein degrades past ~100 words).

_VIEW_POSITIONS = {1: ("in the center",), 2: ("on the left", "on the right"),
                   3: ("on the left", "in the center", "on the right")}
_VIEW_LIGHT = {"morning": "soft morning light", "afternoon": "bright afternoon light",
               "evening": "warm fading evening light", "night": "dim night, long shadows"}
_VIEW_MOOD = {"tense": "tense atmosphere", "dangerous": "menacing atmosphere"}


def _clip(s: str, words: int) -> str:
    return " ".join((s or "").split()[:words])


def _concept(*parts, max_chars: int = 320) -> str:
    """A short human description of WHAT an image shows (its concept), built from the
    given parts: shown clamped as the caption in the chat flow and in full on the
    lightbox and the profile's memories (an image without a concept is just a picture)."""
    text = " ".join(p.strip().rstrip(".") + "." for p in parts if p and p.strip())
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return text


def _focus_character(conn, gid: str, focus: str):
    """The present character the focus text names, if any."""
    pd = repo.get_player(conn, gid)
    low = (focus or "").lower()
    for c in repo.present_characters(conn, gid, pd["location"]):
        if c["name"] and c["name"].lower() in low:
            return c
    return None


def view_prompt(conn, gid: str, focus: str | None = None) -> str:
    """Compose the snapshot prompt from ACTUAL state: scene, present characters, story
    time of day, scene mood, world style. A focus ("what Layla is doing", "that ship")
    becomes THE subject instead of the whole-scene group shot."""
    g = repo.get_game(conn, gid)
    pd = repo.get_player(conn, gid)
    sc = repo.current_scene(conn, gid)
    chars = list(repo.present_characters(conn, gid, pd["location"]))[:3]
    env = _clip(_place_text(sc), 20)
    focus = _clip(_strip_quoted(focus or ""), 20).rstrip(".")
    if focus:
        fc = _focus_character(conn, gid, focus)
        if fc:
            lead = f"Full-body shot of {_clip(_gendered_base(fc), 18).rstrip('.')}, {focus}, in {env}"
        else:
            lead = f"Detailed shot of {focus}, in {env}"
        lead += "" if lead.rstrip().endswith(".") else "."
        people = ""
    elif chars:
        count = ("one person", "two people", "three people")[len(chars) - 1]
        lead = f"Wide full-body shot of {count} in {env}"
        lead += "" if lead.rstrip().endswith(".") else "."
        people = " ".join(f"{p.capitalize()}, {_clip(_gendered_base(c), 18).rstrip('.')}."
                          for p, c in zip(_VIEW_POSITIONS[len(chars)], chars))
    else:
        lead = f"Wide shot of {env}"
        lead += "" if lead.rstrip().endswith(".") else "."
        people = ""
    t = repo.game_time(conn, gid)
    tail = ". ".join(x for x in (
        _VIEW_LIGHT.get(t.get("part") or "", ""),
        _VIEW_MOOD.get(sc["status"] or "", ""),
        g["art_style"] or g["tone"] or "",
        NO_TEXT_GUARD,
    ) if x) + "."
    return " ".join(x for x in (lead, people, tail) if x)


def item_prompt(name: str, description: str, style: str) -> str:
    """A small unlock card for one item: single centered subject, plain backdrop."""
    return ", ".join(x for x in (
        f"Close-up of a single {name}",
        _strip_quoted(description),
        "centered on a plain dark surface, soft dramatic light",
        style, NO_TEXT_GUARD) if x)


# ---------- agentic image prompts (optional, settings.IMAGE_AGENTIC_PROMPTS) ----------
# Hybrid: the text model writes the prompt from live context (it can express poses and
# the just-happened moment, which a template cannot), then CODE enforces the invariants
# (quoted words become rendered lettering, length kills klein, the no-text tail). Any
# failure falls back to the deterministic template prompt.

def _harden_image_prompt(text: str) -> str:
    text = text.strip().strip('"').strip()
    text = _QUOTED.sub("", text).strip()
    text = _clip(text, 90)
    if NO_TEXT_GUARD.lower() not in text.lower():
        text = text.rstrip(".") + ". " + NO_TEXT_GUARD + "."
    return text


def _image_context(conn, gid: str, include_chars: bool, focus: str | None = None) -> str:
    g = repo.get_game(conn, gid)
    pd = repo.get_player(conn, gid)
    sc = repo.current_scene(conn, gid)
    t = repo.game_time(conn, gid)
    lines = [f"PLACE: {_place_text(sc)}",
             f"TIME OF DAY: {t.get('part') or 'day'}    MOOD: {sc['status']}"]
    if (focus or "").strip():
        lines.append(f"THE PLAYER WANTS TO LOOK AT: {_clip(_strip_quoted(focus), 25)}")
    if include_chars:
        chars = list(repo.present_characters(conn, gid, pd["location"]))[:3]
        if chars:
            lines.append("CHARACTERS PRESENT (depict them):")
            lines += [f"- {c['name']}: {_gendered_base(c)}" for c in chars]
        recent = [b for b in repo.recent_beats_at(conn, gid, pd["location"], 6)
                  if not b["private_with"]]
        if recent:
            lines.append("JUST HAPPENED (use for poses and action):")
            lines += [f"- {b['text']}" for b in recent]
    lines.append(f"STYLE: {g['art_style'] or g['tone'] or 'cinematic'}")
    return "\n".join(lines)


def _agentic_prompt(context: str, fallback: str) -> str:
    """One LLM call that writes the image prompt; guarded, with the template as the net."""
    try:
        reply = llm.chat(prompts.build_image_prompt_messages(context),
                         temperature=0.4, max_tokens=140)
        text = (reply.content or "").strip()
    except Exception:
        return fallback
    return _harden_image_prompt(text) if text else fallback
