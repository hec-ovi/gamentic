"""Tool registry + shared result shapes.

A tool is a JSON schema (what the model sees) plus a handler (what applies it),
registered together with the @tool decorator so they can never drift apart:

    @tool({"type": "function", "function": {"name": "heal", ...}})
    def heal(conn, gid, args, actor): ...

Handler signature is uniform: (conn, gid, args, actor) -> result dict
  kind: state | cue | memory | invalid | spawn | kill | reject | image
  text: a short system-beat string to show the player (or None = silent)
  cue:  {id,name,reason} when a character should be given the scene
  reactions: character ids the engine should queue to react
`actor` is None when the narrator/player drives the tool, or the character row when a
character acts (so "you take 5 from Jacker" vs "Jacker takes 5")."""

SCHEMAS: dict[str, dict] = {}
HANDLERS: dict[str, object] = {}

_DAMAGE_DEFAULT = 3
_SCENE_WORDS = ("scene", "room", "here", "the scene", "the room")


def tool(schema: dict):
    """Register a tool's schema and its handler under the schema's function name."""
    name = schema["function"]["name"]
    SCHEMAS[name] = schema

    def deco(fn):
        HANDLERS[name] = fn
        return fn
    return deco


def alias(name: str, target: str) -> None:
    """A second model-facing name for an existing handler (e.g. 'attack' -> apply_damage)."""
    HANDLERS[name] = HANDLERS[target]


def _result(kind, text=None, cue=None, reactions=None):
    return {"kind": kind, "text": text, "cue": cue, "reactions": reactions or []}


def _invalid(reason):
    return {"kind": "invalid", "text": reason, "cue": None, "reactions": []}
