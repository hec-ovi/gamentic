"""The setup face: writing .env from modes, flags and the wizard."""

import json
import os
import re

from conftest import SCHEMA_JS, parse_env, run_cli


def test_anna_yes_writes_true_constant_and_all_defaults(tmp_path, schema):
    envf = tmp_path / ".env"
    r = run_cli("--mode", "anna", "--yes", "--env-file", str(envf))
    assert r.returncode == 0, r.stderr

    vals = parse_env(envf)
    assert vals["ANNA"] == "true"

    const = next(c for c in schema["constants"] if c["key"] == "COMPOSE_PROFILES")
    assert vals["COMPOSE_PROFILES"] == const["value"]
    assert f"# {const['comment']}" in envf.read_text()

    # every non-setByMode setting carries its schema default (anna mode asks
    # only the anna group; gid detection applies only when the gpu group shows)
    for s in schema["settings"]:
        assert s["key"] in vals, f"{s['key']} missing from the written .env"
        if "setByMode" not in s:
            assert vals[s["key"]] == s["default"], s["key"]

    if os.name == "posix":
        assert (envf.stat().st_mode & 0o777) == 0o600


def test_set_with_bad_port_fails_clearly_and_writes_nothing(tmp_path):
    envf = tmp_path / ".env"
    r = run_cli("--mode", "custom", "--yes", "--set", "LLM_TEXT_PORT=70000",
                "--env-file", str(envf))
    assert r.returncode != 0
    assert "LLM_TEXT_PORT" in r.stderr
    assert "1-65535" in r.stderr
    assert not envf.exists()


def test_set_with_bad_bool_fails(tmp_path):
    envf = tmp_path / ".env"
    r = run_cli("--mode", "custom", "--yes", "--set", "ANNA=maybe", "--env-file", str(envf))
    assert r.returncode != 0
    assert "ANNA" in r.stderr and "true" in r.stderr
    assert not envf.exists()


def test_unknown_key_survives_rewrites_under_unmanaged(tmp_path):
    envf = tmp_path / ".env"
    envf.write_text("ANNA=false\nMY_TUNNEL_TOKEN=abc123\n")
    r = run_cli("--mode", "local", "--yes", "--env-file", str(envf))
    assert r.returncode == 0, r.stderr

    text = envf.read_text()
    assert "# --- unmanaged (kept as-is) ---" in text
    assert "MY_TUNNEL_TOKEN=abc123" in text
    assert text.index("unmanaged (kept as-is)") < text.index("MY_TUNNEL_TOKEN")

    # a second rewrite keeps it exactly once (idempotent round-trip)
    r2 = run_cli("--mode", "local", "--yes", "--env-file", str(envf))
    assert r2.returncode == 0, r2.stderr
    assert envf.read_text().count("MY_TUNNEL_TOKEN=abc123") == 1


def test_set_unknown_key_warns_and_is_preserved(tmp_path):
    envf = tmp_path / ".env"
    r = run_cli("--mode", "anna", "--yes", "--set", "WEIRD_KNOB=7", "--env-file", str(envf))
    assert r.returncode == 0
    assert "WEIRD_KNOB" in r.stderr  # warned
    text = envf.read_text()
    assert "WEIRD_KNOB=7" in text
    assert text.index("unmanaged (kept as-is)") < text.index("WEIRD_KNOB=7")


def test_wizard_stdin_produces_same_file_as_flags(tmp_path):
    wizard_env = tmp_path / "wizard.env"
    flags_env = tmp_path / "flags.env"

    # 2 = anna mode, Enter keeps the empty ANNA_API_KEY, y confirms the review
    r = run_cli("--env-file", str(wizard_env), stdin="2\n\ny\n")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "Review" in r.stdout
    assert "sign in once at http://localhost:19001" in r.stdout

    r2 = run_cli("--mode", "anna", "--yes", "--env-file", str(flags_env))
    assert r2.returncode == 0, r2.stderr
    assert wizard_env.read_text() == flags_env.read_text()


def test_wizard_help_and_decline_writes_nothing(tmp_path):
    envf = tmp_path / ".env"
    # '?' on the API key prints its help and re-asks; 'n' declines the write
    r = run_cli("--env-file", str(envf), stdin="2\n?\n\nn\n")
    assert r.returncode != 0
    assert "hackathon-issued key" in r.stdout  # schema help text, rendered verbatim
    assert "Nothing written" in r.stderr + r.stdout
    assert not envf.exists()


def test_json_masks_secrets_but_file_keeps_them(tmp_path):
    envf = tmp_path / ".env"
    r = run_cli("--mode", "anna", "--yes", "--json",
                "--set", "ANNA_API_KEY=sk-verysecret", "--env-file", str(envf))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["values"]["ANNA_API_KEY"] == "********"
    assert "sk-verysecret" not in r.stdout
    assert out["values"]["COMPOSE_PROFILES"]  # constants ride along
    assert parse_env(envf)["ANNA_API_KEY"] == "sk-verysecret"


def test_dry_run_writes_nothing(tmp_path):
    envf = tmp_path / ".env"
    r = run_cli("--mode", "anna", "--yes", "--dry-run", "--json", "--env-file", str(envf))
    assert r.returncode == 0
    assert json.loads(r.stdout)["written"] is False
    assert not envf.exists()


def test_describe_emits_valid_json_with_every_schema_key(schema):
    r = run_cli("--describe")
    assert r.returncode == 0
    d = json.loads(r.stdout)
    described = {s["key"] for s in d["settings"]} | {c["key"] for c in d["constants"]}
    source_keys = set(re.findall(r'"key": "([A-Z][A-Z0-9_]*)"', SCHEMA_JS.read_text()))
    assert source_keys, "schema.js regex oracle found no keys"
    assert source_keys <= described


def test_write_example_contains_every_key_and_help(tmp_path, schema):
    r = run_cli("--write-example", "--env-file", str(tmp_path / ".env"))
    assert r.returncode == 0, r.stderr
    example = tmp_path / ".env.example"
    assert example.exists()
    text = example.read_text()
    for s in schema["settings"]:
        assert f"{s['key']}={s['default']}" in text, s["key"]
    for c in schema["constants"]:
        assert f"{c['key']}={c['value']}" in text
        assert f"# {c['comment']}" in text
    # help rides along as comments (spot-check the load-bearing one)
    assert "The one setting you MUST get right" in text
