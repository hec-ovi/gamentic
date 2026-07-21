"""Request/response shapes. These mirror docs/SPECS.md section 7."""
import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

# Input caps, single-sourced (static-confirmed 2026-06-11: none existed, so one oversized
# request could blow the model context, flood a turn with hundreds of attempts, and store
# megabyte beats). These are schema bounds with friendly 422s; the engine clamps the
# SEMANTICS (damage resolution, per-turn step caps) separately.
MAX_ACTION_CHARS = 4000    # typed freeform action (also echoed verbatim as the player beat)
MAX_SEGMENT_CHARS = 2000   # one tagged segment's text
MAX_WISH_CHARS = 500       # the wish channel
MAX_SEGMENTS = 12          # tagged segments per turn
MAX_ATTACK_AMOUNT = 1000   # player-stated attack force (live: an unbounded amount was an instakill)


class ObjectiveIn(BaseModel):
    text: str
    done: bool = False
    progress: Optional[str] = None


class QuestIn(BaseModel):
    title: str
    description: str = ""
    objectives: list[str] = Field(default_factory=list)

    @field_validator("objectives", mode="before")
    @classmethod
    def _coerce_objectives(cls, v):
        # the model sometimes emits objectives as ints/objects; be tolerant
        if isinstance(v, list):
            return [x if isinstance(x, str) else str(x.get("text", x) if isinstance(x, dict) else x) for x in v]
        return v


class CharacterIn(BaseModel):
    name: str
    persona: str
    description: str = ""         # short public bio shown in the UI
    knowledge: str = ""
    appearance: str = ""          # visual descriptor for the 3-image reference set
    gender: str = ""              # 'female' | 'male' | '' (inferred once at creation if empty)
    origin: str = ""              # backstory; narrator + the character know it, the player discovers it
    relation: str = ""            # what they are to the player at start (stranger, sister, boss...)

    @model_validator(mode="before")
    @classmethod
    def _accept_sex(cls, data):
        # the creator's save_world schema says 'sex' (the model-facing word); map it in
        if isinstance(data, dict) and not data.get("gender") and data.get("sex"):
            data["gender"] = data["sex"]
        return data

    @model_validator(mode="after")
    def _default_description(self):
        # live 2026-06-11: the creator left every description empty and all three
        # character cards (and the world export) rendered a blank line; the persona's
        # first sentence is who they are at a glance, so it backstops the field here,
        # on BOTH creation paths
        if not self.description.strip() and self.persona.strip():
            first = re.split(r"(?<=[.!?])\s", self.persona.strip(), maxsplit=1)[0]
            self.description = first[:160].strip()
        return self
    voice_id: Optional[str] = None
    color: Optional[str] = None
    talkativeness: float = 0.5
    life: int = 10                # characters can be attacked / killed
    max_life: int = 10
    disposition: str = "neutral"  # friendly | neutral | hostile | unknown
    following: bool = False


class LoreIn(BaseModel):
    keys: list[str] = Field(default_factory=list)
    content: str
    constant: bool = False
    priority: int = 0


class PlayerItemIn(BaseModel):
    """A possession the creation chat established the player already holds; seeded into
    the pack at finalize so the opening fiction and the inventory agree (live: a sealed
    ledger existed only in the opening prose and stayed unreachable for 40 turns)."""
    name: str
    description: str = ""


class WorldSheet(BaseModel):
    """The story-creator's output and the create-game payload."""
    title: str
    setting: str = ""
    tone: str = ""
    art_style: str = ""           # world art style/theme applied to all generated images
    narrator_voice_id: Optional[str] = None   # TTS voice for narration
    narrator_persona: str = ""
    opening_scenario: str = ""
    characters: list[CharacterIn] = Field(default_factory=list)
    quests: list[QuestIn] = Field(default_factory=list)
    lore: list[LoreIn] = Field(default_factory=list)
    start_location: str = "start"
    # The model proposes this number, code bounds it (live replay 2026-06-11: the
    # creator filled player_life=1 and the hero spawned one scratch from death).
    # Clamped, not rejected: a 422 here would kill an otherwise perfect finalize.
    player_life: int = 20

    @field_validator("player_life")
    @classmethod
    def _sane_life(cls, v: int) -> int:
        return max(10, min(int(v or 20), 100))
    player_items: list[PlayerItemIn] = Field(default_factory=list)  # opening possessions (seeded at finalize)
    # morning | afternoon | evening | night; '' keeps the clock default. The mapping to
    # story minutes lives with the clock (repo.clock.START_HOURS); unknown words are
    # tolerated and simply ignored there (the model never owns the clock).
    start_time_of_day: str = ""


class EntityRef(BaseModel):
    """An entity chip embedded in a segment: a clickable, non-editable reference the
    player tagged into their text (a character or an item), carrying the real id."""
    kind: str = "character"        # character | item
    id: Optional[str] = None
    name: Optional[str] = None


class Segment(BaseModel):
    """One tagged piece of a player turn. type in: say | do | attack | give | conversation.
    A turn can stack several: [do] go to the table, [say] "nice beer", [attack] X, [give] key -> X."""
    type: str = "do"
    text: str = Field("", max_length=MAX_SEGMENT_CHARS)
    target: Optional[str] = None   # for attack/give/directed say: a character id or name (or "player")
    item: Optional[str] = None     # for give: an item id or name
    # for attack (damage); schema-bounded so a typed or posted force can never instakill
    amount: Optional[int] = Field(None, ge=0, le=MAX_ATTACK_AMOUNT)
    refs: Optional[list[EntityRef]] = None  # entity chips tagged inside this segment's text
    mode: Optional[str] = None     # for conversation: "say" (default) or "do" (a discreet private action)


class ActionIn(BaseModel):
    # Back-compat: a plain freeform action string. OR structured tagged segments.
    action: Optional[str] = Field(None, max_length=MAX_ACTION_CHARS)
    segments: Optional[list[Segment]] = Field(None, max_length=MAX_SEGMENTS)
    # The wish channel: what the player HOPES happens next (never an action). The
    # narrator weighs it by difficulty mode: easy leans into it, hard may ignore it.
    wish: Optional[str] = Field(None, max_length=MAX_WISH_CHARS)


class ContinueIn(BaseModel):
    """Optional body of /continue; the wish channel rides along naturally here."""
    wish: Optional[str] = Field(None, max_length=MAX_WISH_CHARS)


class GameSettingsIn(BaseModel):
    """Live-changeable game settings (PATCH /games/{gid}/settings). Omitted fields
    are left untouched."""
    narrator_gender: Optional[str] = None   # '' (preset default) | 'female' | 'male'
    difficulty: Optional[str] = None        # easy | normal | hard
    history_beats: Optional[int] = None     # verbatim story window (0 = default, 8..400)
    summary_every: Optional[int] = None     # auto-summarize fold cadence in turns (0 = default, 2..50)
    context_tokens: Optional[int] = None    # narrator token budget (0 = off, 4000..120000)
    turn_voices: Optional[int] = None       # characters cued to speak per turn (0 = default, 1..4)
    turn_acts: Optional[int] = None         # times one character may act per turn (0 = default, 1..3)


class ViewIn(BaseModel):
    """The 'See' button payload. focus is optional: what the player wants to look at
    ("what Layla is doing", "that ship on the horizon"); empty = the whole scene."""
    focus: Optional[str] = None


class ExplainIn(BaseModel):
    """'Ask what this is': the player taps a thing and the model explains it in-world,
    from PLAYER-VISIBLE facts only. kind: item | character | scene | quest | goal | beat.
    key: id or name of the thing (beats may use beat_id instead)."""
    kind: str
    key: Optional[str] = None
    beat_id: Optional[str] = None


class CreateMessageIn(BaseModel):
    session_id: str
    message: str


class SpeakIn(BaseModel):
    """The key-safe TTS passthrough: the engine resolves the active audio provider
    server-side (API keys never reach the browser) and returns the audio bytes.
    With provider=local it simply proxies voice-api."""
    text: str = Field(..., min_length=1)
    voice_id: str = ""
    emotion: str = ""
    # optional ownership tag: in local-provider mode it rides to voice-api, whose wav
    # manifest maps filename -> [game_ids] so DELETE /voice/games/{gid} can free the
    # wavs only that game claims. Cloud providers have no wav cache and ignore it.
    game_id: str = ""


class Beat(BaseModel):
    id: str
    turn_index: int
    seq: int
    speaker: str
    speaker_name: Optional[str] = None
    kind: str
    text: str
    location: Optional[str] = None
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    private_with: Optional[str] = None   # if set, a private beat with that character (DM view)
    emotion: str = ""                    # dialogue tone for the voice ('angry', 'whisper', ...)


class PlayerStateOut(BaseModel):
    life: int
    max_life: int
    points: int
    location: str
    inventory: list[dict]
    flags: dict


class QuestOut(BaseModel):
    id: str
    title: str
    description: str
    status: str
    objectives: list[dict]


class CharacterOut(BaseModel):
    id: str
    name: str
    description: str = ""
    gender: str = ""              # 'female' | 'male' | '' - single source of truth (image/prose/voice)
    relation: str = ""            # what they ARE to the player (free 1-2 words: sister, boss, rival...)
    voice_id: Optional[str] = None
    color: Optional[str] = None
    present: bool
    location: str
    life: int = 10
    max_life: int = 10
    alive: bool = True
    disposition: str = "neutral"
    following: bool = False
    face_url: Optional[str] = None
    body_url: Optional[str] = None              # full-body image the UI shows
    body_front_url: Optional[str] = None
    body_side_url: Optional[str] = None
    inventory: list[dict] = Field(default_factory=list)        # revealed items (<= 3)
    traits: list[dict] = Field(default_factory=list)           # personality traits unlocked through play
    context: dict = Field(default_factory=dict)                # this agent's own {used, max} meter
    available_actions: list[dict] = Field(default_factory=list)  # action buttons (<= 3)


class SceneOut(BaseModel):
    id: str
    name: str
    description: str = ""
    background: str = ""          # the place's deeper story (persistent narrator context)
    status: str = "calm"
    image_url: Optional[str] = None
    exits: list[dict] = Field(default_factory=list)            # revealed exits (<= 3)
    items: list[dict] = Field(default_factory=list)            # revealed items (<= 6)
    available_actions: list[dict] = Field(default_factory=list)  # scene action buttons (<= 3)


class GameState(BaseModel):
    game_id: str
    title: str
    status: str = "active"        # story FSM
    scene_status: str = "calm"    # current scene mood FSM
    current_goal: str = ""        # the player's current goal (empty until the narrator sets one)
    scene: SceneOut               # the main card
    narrator_voice_id: Optional[str] = None
    settings: dict = Field(default_factory=dict)  # {narrator_gender, difficulty} (live-changeable)
    context: dict = Field(default_factory=dict)   # {used, max} prompt-token usage meter
    images_enabled: bool = True                   # if true and an image_url is null, art is still coming (show a loader)
    time: dict = Field(default_factory=dict)      # fictional story clock {minutes, day, hour, part, label}
    player: PlayerStateOut
    quests: list[QuestOut]
    characters: list[CharacterOut]


class TurnOut(BaseModel):
    beats: list[Beat]
    state: GameState
    # True when a player stop request cancelled this turn: the whole turn rolled back
    # (no beats, no echo, no clock tick) and the client restores the typed input.
    stopped: bool = False
