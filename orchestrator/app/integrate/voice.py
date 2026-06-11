"""Voice assignment: the narrator preset and per-character designed voices from the
Maya1 registry. Fast (a list lookup / one registry call), so it runs inline at creation.
Best-effort throughout: if voice is down/disabled, the game plays text-only."""
from .. import repo, media
from ..config import settings


def assign_voices_for_game(conn, gid: str) -> None:
    """The narrator gets a preset; each character gets a DESIGNED voice from the Maya1
    registry, composed from their sheet at creation (the same moment their image
    descriptor is fixed), so gender/age/tone always match the character. One character =
    one stored voice (idempotent). Falls back to preset round-robin if the registry is
    unavailable. Best-effort throughout."""
    if not settings.VOICE_ENABLED:
        return
    voices = media.list_voice_ids()
    g = repo.get_game(conn, gid)
    if not g["narrator_voice_id"] and voices:
        repo.set_narrator_voice(conn, gid, "narrator" if "narrator" in voices else voices[0])
    for i, c in enumerate(repo.get_characters(conn, gid)):
        if c["voice_id"]:
            continue
        sheet = " ".join(x for x in (c["description"], c["persona"]) if x).strip() or c["name"]
        vid = media.register_character_voice(
            c["id"], c["name"], sheet,
            gender=repo.character_gender(c))   # the stored single source of truth
        if not vid and voices:
            vid = voices[(i + 1) % len(voices)]
        if vid:
            repo.set_character_voice(conn, c["id"], vid)


def release_game_voices(char_ids: list[str]) -> None:
    """Free the registry entries of a wiped game's characters (best-effort)."""
    for cid in char_ids:
        media.delete_character_voice(cid)


# Gendered narrator voices: full designed descriptions (voice-api treats any voice_id
# containing whitespace as a description), specified per the Maya1 anchoring rules:
# gender, age, pitch with texture, pacing, tone, accent. Distinctive = stable.
NARRATOR_VOICES = {
    "female": ("Female voice, in her 40s, warm low storyteller pitch with a velvet "
               "texture, unhurried measured pacing, intimate confident tone, neutral accent"),
    "male": ("Male voice, in his 50s, deep resonant storyteller pitch with a gravelly "
             "edge, unhurried measured pacing, intimate confident tone, neutral accent"),
}


def apply_narrator_gender(conn, gid: str, gender: str) -> None:
    """Switch the narrator's voice to the chosen gender (takes effect on the next line;
    the frontend reads narrator_voice_id from /state per beat). Empty gender returns to
    the preset default."""
    repo.set_narrator_gender(conn, gid, gender)
    if gender in NARRATOR_VOICES:
        repo.set_narrator_voice(conn, gid, NARRATOR_VOICES[gender])
    else:
        voices = media.list_voice_ids() if settings.VOICE_ENABLED else []
        repo.set_narrator_voice(conn, gid,
                                "narrator" if not voices or "narrator" in voices else voices[0])
