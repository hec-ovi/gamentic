"""Instrumented live playtest: drive a scripted adventure against the REAL model and
print, per turn, the player's action, every tool call the narrator/characters fired,
every beat produced, and the full state delta. This is the 'play it yourself and watch'
tool: run it, read what the brain actually does, find where it stops being logical.

Run with the text stack up:
    PYTHONPATH=. python scripts/playtest.py
    PYTHONPATH=. python scripts/playtest.py --scenario tavern
"""
import argparse
import os
import sys
import tempfile

# isolated temp DB so a playtest never touches the real data
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(prefix="playtest-"), "p.db"))
os.environ.setdefault("IMAGE_ENABLED", "false")
os.environ.setdefault("VOICE_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402
from app import db, llm, main  # noqa: E402

# ---- instrument llm.chat to capture what the model emits, tagged by caller role ----
_real_chat = llm.chat
_LOG = []  # list of {role, content, tools:[(name,args)]}


def _tap(messages, tools=None, tool_choice="auto", temperature=0.8, max_tokens=400, stop=None):
    reply = _real_chat(messages, tools=tools, tool_choice=tool_choice,
                       temperature=temperature, max_tokens=max_tokens, stop=stop)
    sys_txt = messages[0]["content"] if messages else ""
    names = [t["function"]["name"] for t in (tools or [])]
    if "cue_character" in names:
        role = "NARRATOR"
    elif "save_world" in names:
        role = "FINALIZE"
    elif sys_txt.startswith("You narrate the immediate outcome"):
        role = "RESOLVE"
    elif sys_txt.startswith("You are a warm"):
        role = "CREATOR"
    else:
        role = "CHARACTER"
    _LOG.append({"role": role, "content": reply.content,
                 "tools": [(tc.name, tc.arguments) for tc in reply.tool_calls]})
    return reply


llm.chat = _tap

WORLDS = {
    "crypt": {
        "title": "The Sunken Crypt", "setting": "a flooded dwarven crypt", "tone": "grim, tense",
        "narrator_persona": "A solemn, vivid dungeon master who keeps it tight.",
        "opening_scenario": "Cold water laps at your boots as the crypt door groans shut behind you. "
                            "Mara, your dwarven scout, lifts her lantern beside you.",
        "start_location": "crypt entrance", "player_life": 20,
        "characters": [{"name": "Mara", "persona": "A wary dwarven scout, loyal but blunt. Speaks tersely.",
                        "description": "A wary dwarven scout.", "disposition": "friendly",
                        "knowledge": "Knows a secret tunnel behind the altar in the inner chamber."}],
        "quests": [{"title": "Escape the Crypt", "description": "Find a way out.",
                    "objectives": ["Find the altar", "Open the tunnel"]}],
        "lore": [{"keys": ["altar"], "content": "The altar bleeds black water when touched.", "constant": False}],
    },
    "tavern": {
        "title": "The Last Breath", "setting": "a grimy cyberpunk bar on a rain-slick street", "tone": "noir",
        "narrator_persona": "Terse, atmospheric.",
        "opening_scenario": "Neon bleeds through the rain onto the bar floor. Jacker the bartender watches you.",
        "start_location": "the bar", "player_life": 20,
        "characters": [{"name": "Jacker", "persona": "A watchful, cynical bartender who trades in secrets.",
                        "description": "The watchful bartender.", "disposition": "neutral",
                        "knowledge": "Knows where the courier hid the data chip: taped under the back-room table."}],
        "quests": [{"title": "Find the Chip", "description": "Recover the stolen data chip.",
                    "objectives": ["Learn where the chip is", "Recover the chip"]}],
        "lore": [],
    },
}

# Scripted actions designed to exercise transitions: talk, search, MOVE to a new scene,
# pick something up, MOVE BACK (persistence), recruit/keep a follower.
SCRIPTS = {
    "crypt": [
        {"segments": [{"type": "say", "text": "Mara, what do you know about getting out of here?", "target": "Mara"}]},
        {"action": "I search the crumbling walls and the waterline for a hidden passage or any way deeper in."},
        {"action": "I head deeper into the crypt, toward the inner chamber, with Mara following me."},
        {"action": "I look around this new chamber carefully - what's here?"},
        {"action": "I pick up anything useful I can see and pocket it."},
        {"action": "I go back to the crypt entrance to check the water has not risen."},
        {"action": "I touch the altar and brace for whatever happens."},
    ],
    "tavern": [
        {"segments": [{"type": "say", "text": "Jacker, I'm looking for a data chip. What do you know?", "target": "Jacker"}]},
        {"action": "I slide some credits across the bar and ask him to be specific."},
        {"action": "I head to the back room he mentioned."},
        {"action": "I search under the back-room table for the chip."},
        {"action": "I pocket the chip and head back out to the bar."},
        {"action": "I ask Jacker if anyone else is looking for this chip."},
    ],
}


def _delta(prev, cur):
    """Human-readable state delta between two /state snapshots."""
    out = []
    if prev is None:
        return ["(initial)"]
    p, c = prev, cur
    if p["current_goal"] != c["current_goal"]:
        out.append(f"GOAL: {p['current_goal']!r} -> {c['current_goal']!r}")
    if p["scene"]["name"] != c["scene"]["name"]:
        out.append(f"LOCATION: {p['scene']['name']} -> {c['scene']['name']}")
    if p["scene"]["status"] != c["scene"]["status"]:
        out.append(f"SCENE MOOD: {p['scene']['status']} -> {c['scene']['status']}")
    pe = {e["target"] for e in p["scene"]["exits"]}
    ce = {e["target"] for e in c["scene"]["exits"]}
    if pe != ce:
        out.append(f"EXITS: {sorted(pe)} -> {sorted(ce)}")
    pi = {i["name"] for i in p["scene"]["items"]}
    ci = {i["name"] for i in c["scene"]["items"]}
    if pi != ci:
        out.append(f"SCENE ITEMS: {sorted(pi)} -> {sorted(ci)}")
    pinv = {i["name"] for i in p["player"]["inventory"]}
    cinv = {i["name"] for i in c["player"]["inventory"]}
    if pinv != cinv:
        out.append(f"INVENTORY: {sorted(pinv)} -> {sorted(cinv)}")
    if p["player"]["life"] != c["player"]["life"]:
        out.append(f"LIFE: {p['player']['life']} -> {c['player']['life']}")
    for pc in c["characters"]:
        pp = next((x for x in p["characters"] if x["id"] == pc["id"]), None)
        if pp is None:
            out.append(f"NEW CHARACTER: {pc['name']} @ {pc['location']}")
            continue
        if pp["location"] != pc["location"]:
            out.append(f"{pc['name']} MOVED: {pp['location']} -> {pc['location']}")
        if pp["following"] != pc["following"]:
            out.append(f"{pc['name']} following: {pp['following']} -> {pc['following']}")
        if pp["disposition"] != pc["disposition"]:
            out.append(f"{pc['name']} disposition: {pp['disposition']} -> {pc['disposition']}")
        if pp["alive"] != pc["alive"]:
            out.append(f"{pc['name']} alive: {pp['alive']} -> {pc['alive']}")
    return out or ["(no state change)"]


def main_run(scenario: str):
    db.init_db()
    client = TestClient(main.app)
    world = WORLDS[scenario]
    script = SCRIPTS[scenario]

    gid = client.post("/games", json=world).json()["game_id"]
    state = client.get(f"/games/{gid}/state").json()
    print(f"\n{'='*78}\nSCENARIO: {scenario}  title={state['title']!r}  start={state['scene']['name']!r}")
    print(f"opening: {world['opening_scenario']}")
    print(f"chars: {[(c['name'], c['disposition'], c['following']) for c in state['characters']]}")
    print('='*78)

    issues = []
    for i, turn in enumerate(script, 1):
        _LOG.clear()
        prev = state
        desc = turn.get("action") or " + ".join(
            f"{s['type']}:{s.get('text') or s.get('item')}->{s.get('target','')}" for s in turn["segments"])
        print(f"\n----- TURN {i} -----\nPLAYER: {desc}")
        r = client.post(f"/games/{gid}/action", json=turn)
        if r.status_code != 200:
            print(f"  !! HTTP {r.status_code}: {r.text}")
            issues.append(f"turn {i}: HTTP {r.status_code}")
            continue
        beats = r.json()["beats"]
        state = client.get(f"/games/{gid}/state").json()

        # what the model emitted
        for entry in _LOG:
            tag = entry["role"]
            content = (entry["content"] or "").replace("\n", " ")
            tools = ", ".join(f"{n}({_short(a)})" for n, a in entry["tools"]) or "-"
            print(f"  [{tag}] tools: {tools}")
            if content:
                print(f"  [{tag}] prose: {content[:220]}")
            elif tag == "NARRATOR":
                print(f"  [{tag}] prose: <EMPTY - dead air risk>")
        # beats the player actually sees
        for b in beats:
            who = b["speaker_name"] or b["speaker"]
            print(f"    > ({b['kind']}) {who}: {b['text'][:160]}")
        # state delta
        for line in _delta(prev, state):
            print(f"    Δ {line}")

        # logical checks
        segs = turn.get("segments", [])
        directed = any(s.get("type") == "say" and s.get("target") for s in segs)  # routes to a character
        public = (not segs) or any(s["type"] != "whisper" for s in segs)
        has_narr = any(b["kind"] == "narration" for b in beats)
        has_any_voice = any(b["kind"] in ("narration", "dialogue", "action") and b["speaker"] != "player" for b in beats)
        # a free-text public turn must be narrated; a directed say is carried by the character it routes to
        if public and not directed and not has_narr:
            issues.append(f"turn {i}: no narration prose")
        if not has_any_voice:
            issues.append(f"turn {i}: DEAD AIR (no narration/dialogue/action at all)")
        if not state["scene"]["exits"] and i > 1:
            issues.append(f"turn {i}: scene {state['scene']['name']!r} has NO exits (stranding risk)")

    print(f"\n{'='*78}\nFINAL: goal={state['current_goal']!r} loc={state['scene']['name']!r} "
          f"mood={state['scene']['status']} life={state['player']['life']}/{state['player']['max_life']} "
          f"inv={[i['name'] for i in state['player']['inventory']]}")
    quests = [(q["title"], q["status"], [(o["text"], o["done"]) for o in q["objectives"]]) for q in state["quests"]]
    print(f"quests: {quests}")
    print(f"\nLOGICAL ISSUES ({len(issues)}):")
    for x in issues:
        print(f"  - {x}")
    print('='*78)
    return issues


def _short(args: dict) -> str:
    parts = []
    for k, v in (args or {}).items():
        v = str(v)
        parts.append(f"{k}={v[:40]}")
    return " ".join(parts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="crypt", choices=list(WORLDS))
    args = ap.parse_args()
    sys.exit(1 if main_run(args.scenario) else 0)
