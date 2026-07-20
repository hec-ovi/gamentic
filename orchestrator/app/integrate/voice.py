"""Voice identity: engine-owned (docs/shared/inference-providers.md).

The engine composes each character's voice DESIGN from their sheet at creation
(gender-aware, spaced apart within the cast; composer ported from voice-api) and
stores it on the character row. The design then resolves to a voice_id the ACTIVE
audio provider understands (local/fal Maya1 = the design text; openai/elevenlabs =
a deterministic concrete voice seeded by character id). Switching providers
re-resolves every character ONCE; a character never changes voice within a provider.
voice-api's /characters registry is no longer written (deprecated by disuse).
Best-effort throughout: if voice is down/disabled, the game plays text-only."""
from .. import db, repo, media, voice_design
from ..config import settings
from ..providers import base as providers


def _narrator_voice(cfg, gid: str, gender: str) -> str | None:
    """The narrator's voice through the resolver. Local keeps today's preset flow
    ('narrator' from the voice-api catalog); a chosen gender uses the designed
    narrator descriptions; cloud providers resolve the design deterministically."""
    if gender in NARRATOR_VOICES:
        return voice_design.resolve_voice_id(cfg, f"{gid}:narrator:{gender}",
                                             NARRATOR_VOICES[gender])
    if cfg.provider == "local":
        voices = media.list_voice_ids()
        if not voices:
            return None
        return "narrator" if "narrator" in voices else voices[0]
    return voice_design.resolve_voice_id(cfg, f"{gid}:narrator", NARRATOR_VOICES["male"])


def assign_voices_for_game(conn, gid: str) -> None:
    """The narrator gets a preset/designed voice; each character gets a DESIGNED
    voice composed from their sheet at creation (the same moment their image
    descriptor is fixed), stored on their row, and resolved to the active
    provider's voice space. Idempotent: established voices never reshuffle within
    a provider; a provider switch re-resolves from the stored design ONCE.

    DELIBERATE: this module gates on settings.VOICE_ENABLED, NOT
    providers.voice_enabled() (the gate every SPEAK surface uses).
    Identity is engine-owned and composed even with voice off - pure CPU, no audio
    rendered, list_voice_ids() gates itself - so a cloud-born adventure keeps
    designed voices for a later local life (only its narrator voice stays unset:
    the local catalog was absent at creation)."""
    if not settings.VOICE_ENABLED:
        return
    cfg = providers.resolve("audio")
    g = repo.get_game(conn, gid)
    if not g["narrator_voice_id"]:
        v = _narrator_voice(cfg, gid, (g["narrator_gender"] or "").strip())
        if v:
            repo.set_narrator_voice(conn, gid, v)
    chars = repo.get_characters(conn, gid)
    designs = [c["voice_design"] for c in chars if c["voice_design"]]
    for c in chars:
        design = c["voice_design"]
        if not design and c["voice_id"] and not (c["voice_provider"] or ""):
            # legacy row (pre-fold): the registry stored designs AS voice ids;
            # adopt the existing voice as the design so nothing changes mid-game
            design = c["voice_id"]
            repo.set_voice_design(conn, c["id"], design)
            repo.set_character_voice(conn, c["id"], c["voice_id"], provider=cfg.provider)
            designs.append(design)
            continue
        if not design:
            sheet = " ".join(x for x in (c["description"], c["persona"]) if x).strip() or c["name"]
            design = voice_design.compose_design(
                key=c["id"], description=sheet,
                gender=repo.character_gender(c) or None,   # the stored single source of truth
                exclude=designs)
            designs.append(design)
            repo.set_voice_design(conn, c["id"], design)
        if c["voice_id"] and (c["voice_provider"] or "") == cfg.provider:
            continue   # one character = one stable voice per provider
        repo.set_character_voice(
            conn, c["id"], voice_design.resolve_voice_id(cfg, c["id"], design),
            provider=cfg.provider)


def reresolve_voices() -> int:
    """After an audio provider switch (.env change + restart): re-map every character's stored
    design into the new provider's voice space ONCE, and re-resolve each game's
    narrator. Deterministic, so re-running is a no-op. Returns characters updated."""
    if not settings.VOICE_ENABLED:
        return 0
    cfg = providers.resolve("audio")
    updated = 0
    with db.get_conn() as conn:
        for row in repo.list_games(conn):
            gid = row["id"]
            g = repo.get_game(conn, gid)
            if g["narrator_voice_id"]:
                v = _narrator_voice(cfg, gid, (g["narrator_gender"] or "").strip())
                if v:
                    repo.set_narrator_voice(conn, gid, v)
            for c in repo.get_characters(conn, gid):
                design = c["voice_design"] or c["voice_id"]   # legacy: the id WAS the design
                if not design:
                    continue
                if not c["voice_design"]:
                    repo.set_voice_design(conn, c["id"], design)
                if c["voice_id"] and (c["voice_provider"] or "") == cfg.provider:
                    continue
                repo.set_character_voice(
                    conn, c["id"], voice_design.resolve_voice_id(cfg, c["id"], design),
                    provider=cfg.provider)
                updated += 1
    return updated


def release_game_voices(char_ids: list[str]) -> None:
    """Free any LEGACY voice-api registry entries of a wiped game's characters
    (the engine no longer writes that registry; this only keeps old voice-api
    state from piling up). Best-effort."""
    for cid in char_ids:
        media.delete_character_voice(cid)


# Gendered narrator voices: full designed descriptions (the local voice-api treats any
# voice_id containing whitespace as a description), specified per the Maya1 anchoring
# rules: gender, age, pitch with texture, pacing, tone, accent. Distinctive = stable.
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
    cfg = providers.resolve("audio")
    if gender in NARRATOR_VOICES:
        repo.set_narrator_voice(conn, gid, voice_design.resolve_voice_id(
            cfg, f"{gid}:narrator:{gender}", NARRATOR_VOICES[gender]))
    elif cfg.provider == "local":
        voices = media.list_voice_ids() if settings.VOICE_ENABLED else []
        repo.set_narrator_voice(conn, gid,
                                "narrator" if not voices or "narrator" in voices else voices[0])
    else:
        repo.set_narrator_voice(conn, gid, voice_design.resolve_voice_id(
            cfg, f"{gid}:narrator", NARRATOR_VOICES["male"]))
