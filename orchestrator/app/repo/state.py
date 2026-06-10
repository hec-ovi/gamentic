"""The assembled GameState the API serves (everything the UI renders from)."""
from .. import db
from ..config import settings
from . import characters, clock, games, items, players, quests, scenes


def game_state(conn, gid: str) -> dict:
    g = games.get_game(conn, gid)
    p = players.get_player(conn, gid)
    quest_list = [quests.quest_dict(conn, q) for q in quests.get_quests(conn, gid)]
    chars = [
        {"id": c["id"], "name": c["name"], "description": c["description"],
         "voice_id": c["voice_id"], "color": c["color"],
         "present": bool(c["present"]), "location": c["location"],
         "life": c["life"], "max_life": c["max_life"], "alive": bool(c["alive"]),
         "disposition": c["disposition"], "following": bool(c["following"]),
         "face_url": c["face_url"], "body_url": c["body_front_url"],
         "body_front_url": c["body_front_url"], "body_side_url": c["body_side_url"],
         "inventory": items.visible_items(c["inventory"]),
         "traits": characters.character_traits(c),
         "context": {"used": c["context_used"] or 0, "max": settings.LLM_CONTEXT_SIZE},
         "available_actions": characters.available_actions(conn, c, settings.CHAR_ACTION_CAP)}
        for c in characters.get_characters(conn, gid)
    ]
    sc = scenes.current_scene(conn, gid)
    scene = {
        "id": sc["id"], "name": sc["name"], "description": sc["description"],
        "status": sc["status"], "image_url": sc["image_url"],
        "exits": db.loads(sc["exits"], []),
        "items": items.visible_items(sc["items"]),
        "available_actions": scenes.scene_available_actions(conn, sc, settings.SCENE_ACTION_CAP),
    }
    return {
        "game_id": gid,
        "title": g["title"],
        "status": g["status"],
        "scene_status": sc["status"],
        "current_goal": g["current_goal"],
        "scene": scene,
        "narrator_voice_id": g["narrator_voice_id"],
        "settings": {"narrator_gender": g["narrator_gender"] or "",
                     "difficulty": g["difficulty"] or "normal"},
        "context": {"used": g["context_used"] or 0, "max": settings.LLM_CONTEXT_SIZE},
        "images_enabled": settings.IMAGE_ENABLED,  # FE: if true and an image_url is null, show a loader
        "time": clock.game_time(conn, gid),        # fictional story clock {minutes, day, hour, part, label}
        "player": players.player_dict(p),
        "quests": quest_list,
        "characters": chars,
    }
