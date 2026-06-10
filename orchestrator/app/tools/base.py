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

import re

SCHEMAS: dict[str, dict] = {}
HANDLERS: dict[str, object] = {}

_DAMAGE_DEFAULT = 3
_SCENE_WORDS = ("scene", "room", "here", "the scene", "the room")

# Malformed tool streams leak parser debris INTO argument strings (live: a goal arrived
# as "...inner chamber.}<tool_call|><|tool_call>call:cue_character{name:"). Cut from the
# first tool-call marker onward; prose never legitimately contains these.
_ARG_DEBRIS = re.compile(r"\}?\s*<\|?/?tool_call.*$", re.S | re.I)


def clean_arg(v):
    """Scrub model tool-stream debris from a string argument (lists/dicts: per element)."""
    if isinstance(v, str):
        return _ARG_DEBRIS.sub("", v).strip()
    if isinstance(v, list):
        return [clean_arg(x) for x in v]
    if isinstance(v, dict):
        return {k: clean_arg(x) for k, x in v.items()}
    return v


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
