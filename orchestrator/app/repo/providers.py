"""Admin provider overrides: the tiny provider_config key/value table. Keys are
'<modality>.<field>' (e.g. 'image.provider'). The providers layer reads this at CALL
TIME, so a PUT from the admin panel hot-swaps providers with no restart. Resolution
order everywhere: this table -> env -> default."""


def get_provider_overrides(conn) -> dict:
    """All overrides as {key: value}. Blank values are treated as absent (cleared)."""
    rows = conn.execute("SELECT key, value FROM provider_config").fetchall()
    return {r["key"]: r["value"] for r in rows if (r["value"] or "").strip()}


def set_provider_override(conn, key: str, value) -> None:
    """Write one override; an empty/None value DELETES it (the env shows through again)."""
    if value is None or not str(value).strip():
        conn.execute("DELETE FROM provider_config WHERE key=?", (key,))
    else:
        conn.execute(
            "INSERT INTO provider_config (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))
