"""Lore: keyword-matched world facts injected into the narrator within a budget."""
from .. import db


def match_lore(conn, gid: str, text: str, budget: int):
    rows = conn.execute("SELECT * FROM lore WHERE game_id=?", (gid,)).fetchall()
    haystack = text.lower()
    selected = []
    for r in rows:
        keys = db.loads(r["keys"], [])
        if r["constant"] or any(k.lower() in haystack for k in keys):
            selected.append(r)
    selected.sort(key=lambda r: (-r["constant"], -r["priority"]))
    return selected[:budget]
