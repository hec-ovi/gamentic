"""E2E tests drive the REAL entry point: subprocess runs of cli.py.

The schema fixture parses schema.js independently (same slice rule the CLI
documents) so the tests are an oracle on the contract, not on cli.py's parser.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SETUP_DIR = Path(__file__).resolve().parents[1]
CLI = SETUP_DIR / "cli.py"
SCHEMA_JS = SETUP_DIR / "schema.js"


def run_cli(*args, stdin=None):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        input=stdin, capture_output=True, text=True, timeout=120,
    )


def parse_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m:
            values[m.group(1)] = m.group(2)
    return values


@pytest.fixture(scope="session")
def schema():
    text = SCHEMA_JS.read_text()
    start = text.index("{", text.index("=", text.index("window.GAMENTIC_SETUP_SCHEMA")))
    return json.loads(text[start:text.rindex("}") + 1])
