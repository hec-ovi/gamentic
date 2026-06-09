"""Request/response shapes. These mirror docs/SPECS.md section 7."""
from typing import Optional
from pydantic import BaseModel, Field, field_validator


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
    player_life: int = 20


class EntityRef(BaseModel):
    """An entity chip embedded in a segment: a clickable, non-editable reference the
    player tagged into their text (a character or an item), carrying the real id."""
    kind: str = "character"        # character | item
    id: Optional[str] = None
    name: Optional[str] = None


class Segment(BaseModel):
    """One tagged piece of a player turn. type in: say | do | attack | give | whisper.
    A turn can stack several: [do] go to the table, [say] "nice beer", [attack] X, [give] key -> X."""
    type: str = "do"
    text: str = ""
    target: Optional[str] = None   # for attack/give/directed say: a character id or name (or "player")
    item: Optional[str] = None     # for give: an item id or name
    amount: Optional[int] = None   # for attack (damage)
    refs: Optional[list[EntityRef]] = None  # entity chips tagged inside this segment's text
    mode: Optional[str] = None     # for whisper: "say" (default) or "do" (a discreet private action)


class ActionIn(BaseModel):
    # Back-compat: a plain freeform action string. OR structured tagged segments.
    action: Optional[str] = None
    segments: Optional[list[Segment]] = None


class CreateMessageIn(BaseModel):
    session_id: str
    message: str


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
    available_actions: list[dict] = Field(default_factory=list)  # action buttons (<= 3)


class SceneOut(BaseModel):
    id: str
    name: str
    description: str = ""
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
    context: dict = Field(default_factory=dict)   # {used, max} prompt-token usage meter
    images_enabled: bool = True                   # if true and an image_url is null, art is still coming (show a loader)
    time: dict = Field(default_factory=dict)      # fictional story clock {minutes, day, hour, part, label}
    player: PlayerStateOut
    quests: list[QuestOut]
    characters: list[CharacterOut]


class TurnOut(BaseModel):
    beats: list[Beat]
    state: GameState
