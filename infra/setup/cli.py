#!/usr/bin/env python3
"""gamentic-setup: the CLI face of the ONE config schema (infra/setup/schema.js).

Both faces (this CLI and setup.html) render that schema and write the same .env;
neither carries settings of its own. Stdlib only, Python 3.10+.

  cli.py                      interactive wizard
  cli.py --mode anna --yes    non-interactive (agents drive this)
  cli.py doctor               validate the current .env + this host
"""

import argparse
import getpass
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCHEMA_PATH = HERE / "schema.js"
MASK = "********"
# the gpu group's help promises detection; these are the keys it covers
GID_GROUPS = {"RENDER_GID": "render", "VIDEO_GID": "video"}
ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def warn(msg):
    print(f"[warn] {msg}", file=sys.stderr)


def load_schema():
    try:
        text = SCHEMA_PATH.read_text(encoding="utf-8")
        eq = text.index("=", text.index("window.GAMENTIC_SETUP_SCHEMA"))
        start = text.index("{", eq)
        end = text.rindex("}")
        return json.loads(text[start:end + 1])
    except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
        sys.exit(
            f"FATAL: cannot read {SCHEMA_PATH} as 'window.GAMENTIC_SETUP_SCHEMA = {{pure JSON}};'\n"
            f"  {e}\n"
            "The schema is the one source both setup faces render from; restore it from git."
        )


def setting_map(schema):
    return {s["key"]: s for s in schema["settings"]}


def managed_keys(schema):
    return set(setting_map(schema)) | {c["key"] for c in schema["constants"]}


def visible_groups(schema, mode):
    return [g for g in schema["groups"] if mode in g["modes"]]


def group_settings(schema, group_id):
    return [s for s in schema["settings"] if s["group"] == group_id]


def askable(setting, mode):
    if mode == "custom":
        return True
    if setting.get("advanced"):
        return False
    return mode not in setting.get("setByMode", {})


def validate(setting, raw):
    """Normalize one value for the setting's type, or raise ValueError."""
    raw = str(raw).strip()
    if "\n" in raw or "\r" in raw:
        raise ValueError(f"{setting['key']}: value must be a single line")
    t = setting["type"]
    if t == "bool":
        low = raw.lower()
        if low in ("y", "yes", "true"):
            return "true"
        if low in ("n", "no", "false"):
            return "false"
        raise ValueError(f"{setting['key']}: expected y/n/true/false, got {raw!r}")
    if t in ("int", "port"):
        try:
            n = int(raw)
        except ValueError:
            raise ValueError(f"{setting['key']}: expected a whole number, got {raw!r}") from None
        if t == "port" and not 1 <= n <= 65535:
            raise ValueError(f"{setting['key']}: a port must be 1-65535, got {raw!r}")
        return str(n)
    if t == "choice" and raw not in setting["choices"]:
        raise ValueError(f"{setting['key']}: must be one of {', '.join(setting['choices'])}, got {raw!r}")
    return raw


def path_warning(setting, value, values):
    if not value:
        return None
    if setting["type"] == "path":
        p = Path(value)
    elif setting["type"] == "path-relative":
        p = Path(values.get("MODELS_DIR", "")) / value
    else:
        return None
    if not p.exists():
        return f"{setting['key']}: {p} does not exist on this machine (kept anyway)"
    return None


def read_env(path, managed):
    """Existing .env -> (managed values, unknown lines kept verbatim)."""
    values, unmanaged = {}, []
    if not path.exists():
        return values, unmanaged
    # utf-8-sig: a Windows-saved .env may lead with a BOM that would otherwise
    # hide the first key (the HTML face's JS trim() strips it; stay equivalent)
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = ENV_LINE.match(line)
        if not m:
            continue
        if m.group(1) in managed:
            values[m.group(1)] = m.group(2).strip()
        else:
            unmanaged.append(line.strip())
    return values, unmanaged


def host_gid(group_name):
    if sys.platform != "linux":
        return None
    try:
        import grp
        return str(grp.getgrnam(group_name).gr_gid)
    except (ImportError, KeyError):
        return None


def compute_values(schema, mode, existing, sets):
    """defaults < existing .env < setByMode(mode) < gid detection < --set."""
    values = {s["key"]: s["default"] for s in schema["settings"]}
    values.update(existing)
    if mode != "custom":
        for s in schema["settings"]:
            if mode in s.get("setByMode", {}):
                values[s["key"]] = s["setByMode"][mode]
    if any(g["id"] == "gpu" for g in visible_groups(schema, mode)):
        for key, gname in GID_GROUPS.items():
            if key not in existing and key not in sets:
                got = host_gid(gname)
                if got:
                    values[key] = got
    values.update(sets)
    return values


def parse_sets(schema, pairs):
    smap = setting_map(schema)
    const_keys = {c["key"] for c in schema["constants"]}
    sets, extra_unmanaged = {}, []
    for pair in pairs or []:
        if "=" not in pair:
            sys.exit(f"--set needs KEY=VALUE, got {pair!r}")
        key, val = pair.split("=", 1)
        key = key.strip()
        if key in smap:
            try:
                sets[key] = validate(smap[key], val)
            except ValueError as e:
                sys.exit(f"--set {pair!r}: {e}")
        elif key in const_keys:
            warn(f"--set {key} ignored: constants are written from the schema, never set")
        else:
            warn(f"--set {key}: not in the schema, kept under the unmanaged section")
            extra_unmanaged.append(f"{key}={val}")
    return sets, extra_unmanaged


def masked(schema, values):
    smap = setting_map(schema)
    return {
        k: MASK if v and smap.get(k, {}).get("type") == "secret" else v
        for k, v in values.items()
    }


def render_env(schema, values, unmanaged, mode):
    group_ids = {g["id"] for g in schema["groups"]}
    stray = [s["key"] for s in schema["settings"] if s["group"] not in group_ids]
    if stray:
        sys.exit(f"FATAL: schema settings reference unknown groups: {stray}")
    out = [
        f"# Gamentic stack config. Written by gamentic-setup (mode: {mode}).",
        "# Re-run ./gamentic-setup to change it; the one schema is infra/setup/schema.js.",
        "",
    ]
    for g in schema["groups"]:
        out.append(f"# --- {g['label']} ---")
        for s in group_settings(schema, g["id"]):
            out.append(f"# {s['prompt']}")
            out.append(f"{s['key']}={values[s['key']]}")
        out.append("")
    for c in schema["constants"]:
        out.append(f"# {c['comment']}")
        out.append(f"{c['key']}={c['value']}")
    if unmanaged:
        out.append("")
        out.append("# --- unmanaged (kept as-is) ---")
        out.extend(unmanaged)
    out.append("")
    return "\n".join(out)


def render_example(schema):
    out = [
        "# Gamentic stack config. GENERATED from infra/setup/schema.js by:  ./gamentic-setup --write-example",
        "# Quick start: ./gamentic-setup (wizard). By hand: cp .env.example .env and edit.",
        "",
    ]
    for g in schema["groups"]:
        out.append(f"# --- {g['label']} ---")
        for s in group_settings(schema, g["id"]):
            out.append(f"# {s['key']}: {s['prompt']}")
            for line in textwrap.wrap(s["help"], 92):
                out.append(f"#   {line}")
            out.append(f"{s['key']}={s['default']}")
        out.append("")
    for c in schema["constants"]:
        out.append(f"# {c['comment']}")
        out.append(f"{c['key']}={c['value']}")
    out.append("")
    return "\n".join(out)


def write_env(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    if os.name == "posix":
        os.chmod(path, 0o600)  # O_CREAT mode does not touch a pre-existing file


# ---------- interactive wizard ----------

def ask_line(prompt):
    try:
        return input(prompt)
    except EOFError:
        sys.exit("\nAborted: input ended before the wizard finished. Nothing written.")


def ask_secret_line(prompt):
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return ask_line(prompt)


def show_help(text):
    for line in textwrap.wrap(text, 76):
        print(f"    {line}")


def ask_mode(schema):
    modes = schema["modes"]
    print("Pick a mode ('?' explains each):")
    for i, m in enumerate(modes, 1):
        print(f"  {i}) {m['label']}")
    while True:
        raw = ask_line("Mode [1]: ").strip()
        if raw == "?":
            for m in modes:
                print(f"  {m['label']}:")
                show_help(m["help"])
            continue
        if raw == "":
            return modes[0]["id"]
        if raw.isdigit() and 1 <= int(raw) <= len(modes):
            return modes[int(raw) - 1]["id"]
        if raw in [m["id"] for m in modes]:
            return raw
        print(f"  pick a number 1-{len(modes)}")


def ask_setting(s, current, values):
    t = s["type"]
    if t == "choice":
        print(f"{s['prompt']}:")
        for i, c in enumerate(s["choices"], 1):
            print(f"  {i}) {c}")
    while True:
        if t == "secret":
            shown = MASK if current else "empty"
            raw = ask_secret_line(f"{s['prompt']} [{shown}, Enter keeps]: ")
        elif t == "bool":
            raw = ask_line(f"{s['prompt']} (y/n) [{current}]: ")
        else:
            raw = ask_line(f"{s['prompt']} [{current}]: ")
        raw = raw.strip()
        if raw == "?":
            show_help(s["help"])
            continue
        if raw == "":
            val = current
        else:
            if t == "choice" and raw.isdigit() and 1 <= int(raw) <= len(s["choices"]):
                raw = s["choices"][int(raw) - 1]
            try:
                val = validate(s, raw)
            except ValueError as e:
                print(f"  {e}")
                continue
        w = path_warning(s, val, values)
        if w:
            print(f"  [warn] {w}")
        return val


def wizard(schema, args, env_path):
    existing, unmanaged = read_env(env_path, managed_keys(schema))
    sets, extra = parse_sets(schema, args.set)
    unmanaged = merge_unmanaged(unmanaged, extra)

    print("Gamentic setup. Enter keeps the value in [brackets]; '?' explains a question.")
    print(f"Target file: {env_path}")
    print()
    mode = args.mode or ask_mode(schema)
    values = compute_values(schema, mode, existing, sets)

    for g in visible_groups(schema, mode):
        to_ask = [s for s in group_settings(schema, g["id"])
                  if askable(s, mode) and s["key"] not in sets]
        if not to_ask:
            continue
        print(f"\n== {g['label']} ==")
        for s in to_ask:
            values[s["key"]] = ask_setting(s, values[s["key"]], values)

    print("\n--- Review (everything not shown is written with its default) ---")
    disp = masked(schema, values)
    for g in visible_groups(schema, mode):
        print(f"{g['label']}:")
        for s in group_settings(schema, g["id"]):
            print(f"  {s['key']} = {disp[s['key']]}")
    for c in schema["constants"]:
        print(f"{c['key']} = {c['value']}   (constant)")
    if unmanaged:
        print(f"unmanaged keys kept as-is: {len(unmanaged)}")

    answer = ask_line(f"\nWrite {env_path}? [Y/n] ").strip().lower()
    if answer not in ("", "y", "yes"):
        sys.exit("Nothing written.")
    finish(schema, mode, values, unmanaged, env_path, args)


def merge_unmanaged(unmanaged, extra):
    extra_keys = {line.split("=", 1)[0] for line in extra}
    kept = [l for l in unmanaged if ENV_LINE.match(l).group(1) not in extra_keys]
    return kept + extra


def finish(schema, mode, values, unmanaged, env_path, args):
    text = render_env(schema, values, unmanaged, mode)
    if not args.dry_run:
        write_env(env_path, text)
    if args.json:
        full = dict(values)
        for c in schema["constants"]:
            full[c["key"]] = c["value"]
        print(json.dumps({
            "mode": mode,
            "envFile": str(env_path),
            "written": not args.dry_run,
            "values": masked(schema, full),
            "unmanaged": unmanaged,
        }, indent=2))
        return
    if args.dry_run:
        print(f"[dry-run] nothing written. {env_path} would be:\n")
        print(text)
    else:
        print(f"\nWrote {env_path}")
    print(schema["doneMessage"])
    if mode == "anna":
        print("Anna mode: after the stack is up, sign in once at http://localhost:19001 (the agent's Web UI).")


def run_setup(args):
    schema = load_schema()
    env_path = Path(args.env_file).resolve() if args.env_file else ROOT / schema["envFile"]

    if args.describe:
        print(json.dumps(schema, indent=2))
        return
    if args.write_example:
        target = env_path.parent / ".env.example"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_example(schema), encoding="utf-8")
        print(f"Wrote {target}")
        return
    if args.ui:
        page = ROOT / "setup.html"
        if not page.exists():
            sys.exit(f"{page} does not exist")
        import webbrowser
        webbrowser.open(page.as_uri())
        print(f"Opened {page} in your browser.")
        return

    if not args.yes:
        wizard(schema, args, env_path)
        return

    existing, unmanaged = read_env(env_path, managed_keys(schema))
    sets, extra = parse_sets(schema, args.set)
    unmanaged = merge_unmanaged(unmanaged, extra)
    mode = args.mode
    if not mode:
        mode = schema["modes"][0]["id"]
        warn(f"no --mode given, using '{mode}' (the shipping default)")
    values = compute_values(schema, mode, existing, sets)
    for g in visible_groups(schema, mode):
        for s in group_settings(schema, g["id"]):
            w = path_warning(s, values[s["key"]], values)
            if w:
                warn(w)
    finish(schema, mode, values, unmanaged, env_path, args)


# ---------- doctor ----------

def looks_secret(schema, key):
    smap = setting_map(schema)
    if smap.get(key, {}).get("type") == "secret":
        return True
    up = key.upper()
    return any(tag in up for tag in ("KEY", "SECRET", "PASSWORD", "TOKEN"))


def run_doctor(argv):
    ap = argparse.ArgumentParser(
        prog="gamentic-setup doctor",
        description="Validate the current .env and this host for the configured mode.")
    ap.add_argument("--env-file", help="env file to check (default: <repo>/.env)")
    ap.add_argument("--db", help="orchestrator sqlite db (default: <repo>/orchestrator/data/gamentic.db)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--clear-overrides", action="store_true",
                    help="delete leftover provider_config rows from the removed admin "
                         "panel (no runtime effect anymore; cleared for tidiness)")
    args = ap.parse_args(argv)

    schema = load_schema()
    smap = setting_map(schema)
    env_path = Path(args.env_file).resolve() if args.env_file else ROOT / schema["envFile"]
    db_path = Path(args.db).resolve() if args.db else ROOT / "orchestrator" / "data" / "gamentic.db"

    checks = []
    def ok(m): checks.append(("ok", m))
    def wa(m): checks.append(("warn", m))
    def fa(m): checks.append(("fail", m))

    if env_path.exists():
        ok(f"{env_path} found")
        env, _ = read_env(env_path, managed_keys(schema))
    else:
        fa(f"{env_path} does not exist; run ./gamentic-setup first")
        env = {}

    def val(key):
        return env.get(key, smap[key]["default"])

    anna = env.get("ANNA")
    if anna in ("true", "false"):
        ok(f"ANNA={anna} (literal)")
    else:
        found = repr(anna) if anna is not None else "missing"
        fa(f"ANNA must be the LITERAL true or false (found: {found}); compose profiles match "
           "only the literals, so anything else starts NO inference services. Fix: ./gamentic-setup")

    want = next(c["value"] for c in schema["constants"] if c["key"] == "COMPOSE_PROFILES")
    got = env.get("COMPOSE_PROFILES")
    if got == want:
        ok("COMPOSE_PROFILES matches the schema constant")
    else:
        found = repr(got) if got is not None else "missing"
        fa(f"COMPOSE_PROFILES must be exactly {want!r} (found: {found}); re-run ./gamentic-setup to restore it")

    if shutil.which("docker") is None:
        fa("docker not found on PATH; Docker is the project's hard prerequisite")
    else:
        for cmd, label in ((["docker", "--version"], "docker"),
                           (["docker", "compose", "version"], "docker compose")):
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                p = None
            if p and p.returncode == 0:
                ok(f"{label}: {p.stdout.strip().splitlines()[0]}")
            else:
                fa(f"'{' '.join(cmd)}' failed; install or fix Docker (compose v2 plugin required)")

    if anna == "false":
        models = Path(val("MODELS_DIR"))
        if models.is_dir():
            ok(f"MODELS_DIR {models} exists")
        else:
            fa(f"MODELS_DIR {models} does not exist")
        text_model = models / val("LLM_TEXT_MODEL")
        if text_model.is_file():
            ok(f"text model file {text_model} exists")
        else:
            fa(f"text model file missing: {text_model} (LLM_TEXT_MODEL is the one setting "
               "you MUST get right for local play)")
        comfy = Path(val("COMFY_MODELS_DIR"))
        if comfy.is_dir():
            ok(f"COMFY_MODELS_DIR {comfy} exists")
        else:
            fa(f"COMFY_MODELS_DIR {comfy} does not exist")
        if Path("/dev/dri").exists():
            ok("/dev/dri present (GPU render nodes)")
        else:
            fa("/dev/dri missing: no GPU render nodes, the local stack cannot run. "
               "No GPU? Use anna mode: ./gamentic-setup --mode anna")
        if Path("/dev/kfd").exists():
            ok("/dev/kfd present (ROCm compute)")
        else:
            wa("/dev/kfd missing: ROCm compute unavailable (ComfyUI images need it)")
        if sys.platform == "linux":
            for key, gname in GID_GROUPS.items():
                actual = host_gid(gname)
                if actual is None:
                    wa(f"group '{gname}' not found on this host (getent group {gname}); "
                       f"containers may not reach the GPU")
                elif actual != val(key):
                    wa(f"{key}={val(key)} but getent group {gname} says {actual}; containers "
                       f"may lose GPU access. Fix: set {key}={actual} in .env (re-run ./gamentic-setup)")
                else:
                    ok(f"{key}={actual} matches group '{gname}'")

    for s in schema["settings"]:
        if s["type"] != "port":
            continue
        raw = val(s["key"])
        try:
            port = int(raw)
        except ValueError:
            wa(f"{s['key']}={raw!r} is not a number, skipping the port probe")
            continue
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            ok(f"port {port} ({s['key']}) is free")
        except OSError:
            wa(f"port {port} ({s['key']}) is in use (fine if the stack is already up)")
        finally:
            probe.close()

    rows, db_err = [], None
    if db_path.exists():
        try:
            con = sqlite3.connect(db_path)
            has_table = con.execute(
                "select name from sqlite_master where type='table' and name='provider_config'"
            ).fetchone()
            if has_table:
                rows = con.execute("select key, value from provider_config").fetchall()
                if rows and args.clear_overrides:
                    con.execute("delete from provider_config")
                    con.commit()
            con.close()
        except sqlite3.Error as e:
            db_err = str(e)
    if db_err:
        wa(f"could not inspect {db_path}: {db_err}")
    elif rows and args.clear_overrides:
        ok(f"cleared {len(rows)} leftover admin-panel row(s) from provider_config in {db_path}")
    elif rows:
        listing = ", ".join(
            f"{k}={MASK if looks_secret(schema, k) else v}" for k, v in rows)
        wa(f"leftover provider_config rows from the removed admin panel in {db_path}: "
           f"{listing}. They have NO runtime effect (the orchestrator reads only .env); "
           f"clear them for tidiness with: ./gamentic-setup doctor --clear-overrides")
    else:
        ok("no leftover admin-panel rows")

    fails = sum(1 for level, _ in checks if level == "fail")
    warns = sum(1 for level, _ in checks if level == "warn")
    if args.json:
        print(json.dumps({
            "checks": [{"level": level, "msg": msg} for level, msg in checks],
            "failures": fails,
            "warnings": warns,
        }, indent=2))
    else:
        for level, msg in checks:
            print(f"[{level}] {msg}")
        print(f"\n{fails} failure(s), {warns} warning(s).")
    sys.exit(1 if fails else 0)


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "doctor":
        run_doctor(argv[1:])
        return
    schema_modes = [m["id"] for m in load_schema()["modes"]]
    ap = argparse.ArgumentParser(
        prog="gamentic-setup",
        description="Configure the Gamentic stack (.env) from the one schema. "
                    "No flags = interactive wizard.",
        epilog="Subcommand: doctor (validate .env + host; supports --json, --clear-overrides).")
    ap.add_argument("--mode", choices=schema_modes, help="setup mode (skips the mode question)")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE",
                    help="set one value (repeatable; validated against the schema)")
    ap.add_argument("--yes", action="store_true",
                    help="non-interactive: mode + sets + existing values + defaults")
    ap.add_argument("--json", action="store_true",
                    help="print the resulting config as JSON (secrets masked)")
    ap.add_argument("--dry-run", action="store_true", help="do not write the env file")
    ap.add_argument("--describe", action="store_true", help="dump the parsed schema JSON and exit")
    ap.add_argument("--write-example", action="store_true",
                    help="regenerate .env.example from the schema and exit")
    ap.add_argument("--ui", action="store_true", help="open setup.html in the browser and exit")
    ap.add_argument("--env-file", metavar="PATH", help="target env file (default: <repo>/.env)")
    run_setup(ap.parse_args(argv))


if __name__ == "__main__":
    main()
