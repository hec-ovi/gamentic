"""Quests and objectives."""
from .base import _id


def get_quests(conn, gid: str):
    return conn.execute("SELECT * FROM quests WHERE game_id=?", (gid,)).fetchall()


def get_objectives(conn, qid: str):
    return conn.execute("SELECT * FROM objectives WHERE quest_id=?", (qid,)).fetchall()


def quest_dict(conn, q) -> dict:
    objs = [
        {"id": o["id"], "text": o["text"], "done": bool(o["done"]), "progress": o["progress"]}
        for o in get_objectives(conn, q["id"])
    ]
    return {"id": q["id"], "title": q["title"], "description": q["description"],
            "status": q["status"], "objectives": objs}


def start_quest(conn, gid: str, title: str, description: str, objectives: list[str]) -> str:
    qid = _id()
    conn.execute("INSERT INTO quests (id, game_id, title, description) VALUES (?,?,?,?)",
                 (qid, gid, title, description))
    for text in objectives or []:
        conn.execute("INSERT INTO objectives (id, quest_id, text) VALUES (?,?,?)", (_id(), qid, text))
    return qid


def update_objective(conn, oid: str, done: bool, progress: str | None) -> bool:
    cur = conn.execute("UPDATE objectives SET done=?, progress=? WHERE id=?",
                       (int(done), progress, oid))
    return cur.rowcount > 0


def objective_text(conn, oid: str) -> str:
    row = conn.execute("SELECT text FROM objectives WHERE id=?", (oid,)).fetchone()
    return row["text"] if row else ""


def quest_title(conn, qid: str) -> str:
    row = conn.execute("SELECT title FROM quests WHERE id=?", (qid,)).fetchone()
    return row["title"] if row else ""


def set_quest_status(conn, qid: str, status: str) -> bool:
    cur = conn.execute("UPDATE quests SET status=? WHERE id=?", (status, qid))
    return cur.rowcount > 0
