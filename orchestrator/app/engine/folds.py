"""Background memory folds: the rolling game recap and the per-character witnessed
recaps. Scheduled after turns by main.py; each fold is one LLM call, stale-guarded."""
from .. import db, repo, prompts, llm
from ..config import settings
from . import parsing


def maybe_update_summary(gid: str) -> None:
    """Background (scheduled after turns): fold story older than the newest turns into
    the rolling facts-only recap, so the narrator always knows the WHOLE story at a
    bounded token cost. One LLM call per fold; failures keep the previous recap and
    retry on a later turn. Characters have their own folds (witnessed beats only):
    maybe_update_character_summaries below."""
    if not settings.SUMMARY_ENABLED:
        return
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        if not g:
            return
        latest = repo.next_turn_index(conn, gid) - 1
        done_through = g["summarized_through"] or 0
        target = latest - settings.SUMMARY_KEEP_TURNS
        if target - done_through < repo.effective_summary_every(g):
            return
        rows = repo.beats_between(conn, gid, done_through, target)
        if not rows:
            return
        prev = (g["story_summary"] or "").strip()
        transcript = "\n".join(prompts._render_beat(b) for b in rows)
    try:
        reply = llm.chat(prompts.build_summary_messages(prev, transcript),
                         temperature=0.3, max_tokens=settings.SUMMARY_MAX_TOKENS)
    except Exception:
        return
    text = parsing.clean_prose(reply.content or "")   # drift safety: junk never becomes memory
    if not text:
        return
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        # the window must not have moved while the LLM ran: a concurrent fold or a
        # history reset makes this result stale (it covers beats that no longer follow
        # the stored recap); skip and let a later turn fold fresh
        if g and (g["summarized_through"] or 0) == done_through:
            repo.set_story_summary(conn, gid, text, target)


def maybe_update_character_summaries(gid: str) -> None:
    """Background (scheduled after turns, beside maybe_update_summary): fold what each
    ALIVE character WITNESSED into their private second-person recap. Built only from
    witnessed beats, so another character's whispers can never enter. The cadence is
    counted in witnessed BEATS (CHAR_SUMMARY_EVERY); the fold cursor (summarized_through)
    is a beats turn_index, the same unit as the game recap. A character folds only when
    they crossed the threshold - in practice only story-central characters - so this
    never adds a per-turn LLM call for the whole cast."""
    if not settings.CHAR_SUMMARY_ENABLED:
        return
    folds = []
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return
        latest = repo.next_turn_index(conn, gid) - 1
        target = latest - settings.CHAR_SUMMARY_KEEP_TURNS   # newest turns never folded
        for c in repo.get_characters(conn, gid):
            if not c["alive"]:
                continue
            done = c["summarized_through"] or 0
            if target <= done:
                continue
            rows = repo.witnessed_beats_between(conn, gid, c["id"], done, target)
            if len(rows) < settings.CHAR_SUMMARY_EVERY:
                continue
            folds.append({"cid": c["id"], "name": c["name"], "done": done,
                          "prev": (c["memory_summary"] or "").strip(),
                          "transcript": "\n".join(prompts._render_beat(b) for b in rows)})
    for f in folds:
        try:
            reply = llm.chat(
                prompts.build_character_summary_messages(f["name"], f["prev"], f["transcript"]),
                temperature=0.3, max_tokens=settings.CHAR_SUMMARY_MAX_TOKENS)
        except Exception:
            continue   # keep the previous recap; a later turn retries
        text = parsing.clean_prose(reply.content or "")   # drift safety: junk never becomes memory
        if not text:
            continue
        with db.get_conn() as conn:
            c = repo.get_character(conn, f["cid"])
            # stale-fold guard (same as the game recap): if a rival fold or a history
            # reset moved this character's cursor while the LLM ran, skip the write
            if c and (c["summarized_through"] or 0) == f["done"]:
                repo.set_character_summary(conn, f["cid"], text, target)
