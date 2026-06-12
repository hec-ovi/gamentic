"""The doctor face: validating .env + host, and the stale-override sweep."""

import json
import sqlite3

from conftest import run_cli


def anna_env(tmp_path):
    envf = tmp_path / ".env"
    r = run_cli("--mode", "anna", "--yes", "--env-file", str(envf))
    assert r.returncode == 0, r.stderr
    return envf


def doctor_json(envf, db, *extra):
    r = run_cli("doctor", "--env-file", str(envf), "--db", str(db), "--json", *extra)
    d = json.loads(r.stdout)
    # the documented exit contract: 1 on hard failures, 0 with warnings
    assert r.returncode == (1 if d["failures"] else 0)
    return r, d


def test_doctor_passes_on_fresh_anna_env(tmp_path):
    envf = anna_env(tmp_path)
    r, d = doctor_json(envf, tmp_path / "absent.db")
    assert d["failures"] == 0
    assert any("ANNA=true (literal)" in c["msg"] for c in d["checks"])


def test_doctor_flags_anna_1_as_hard_failure(tmp_path):
    envf = anna_env(tmp_path)
    envf.write_text(envf.read_text().replace("ANNA=true", "ANNA=1"))
    r, d = doctor_json(envf, tmp_path / "absent.db")
    assert r.returncode == 1
    fails = [c for c in d["checks"] if c["level"] == "fail"]
    assert any("ANNA" in c["msg"] and "LITERAL" in c["msg"] for c in fails)

    # human-readable face carries the same verdict
    r2 = run_cli("doctor", "--env-file", str(envf), "--db", str(tmp_path / "absent.db"))
    assert r2.returncode == 1
    assert "[fail]" in r2.stdout


def test_doctor_flags_tampered_compose_profiles(tmp_path):
    envf = anna_env(tmp_path)
    envf.write_text(envf.read_text().replace(
        "COMPOSE_PROFILES=local-inference-anna-false,anna-agent-anna-true",
        "COMPOSE_PROFILES=oops"))
    r, d = doctor_json(envf, tmp_path / "absent.db")
    assert r.returncode == 1
    assert any(c["level"] == "fail" and "COMPOSE_PROFILES" in c["msg"] for c in d["checks"])


def test_doctor_missing_env_is_hard_failure(tmp_path):
    r, d = doctor_json(tmp_path / "nope.env", tmp_path / "absent.db")
    assert r.returncode == 1
    assert any("run ./gamentic-setup first" in c["msg"] for c in d["checks"])


def make_override_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE provider_config (key TEXT PRIMARY KEY, value TEXT)")
    con.executemany("INSERT INTO provider_config VALUES (?, ?)", rows)
    con.commit()
    con.close()


def test_doctor_warns_on_stale_overrides_and_clear_removes_them(tmp_path):
    envf = anna_env(tmp_path)
    db = tmp_path / "gamentic.db"
    make_override_db(db, [("text_api_key", "sk-oldsecret"), ("text_provider", "openai")])

    r, d = doctor_json(envf, db)
    over = [c for c in d["checks"]
            if c["level"] == "warn" and "leftover provider_config rows" in c["msg"]]
    assert len(over) == 1
    assert "text_api_key" in over[0]["msg"]
    assert "text_provider=openai" in over[0]["msg"]   # non-secret shown
    assert "sk-oldsecret" not in r.stdout             # secret masked

    r2, d2 = doctor_json(envf, db, "--clear-overrides")
    assert any("cleared 2" in c["msg"] for c in d2["checks"])
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM provider_config").fetchone()[0] == 0
    con.close()

    r3, d3 = doctor_json(envf, db)
    assert not any("leftover provider_config rows" in c["msg"] for c in d3["checks"])
    assert any("no leftover admin-panel rows" in c["msg"] for c in d3["checks"])
