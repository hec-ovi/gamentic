"""Shared primitives for the repo package: ids and name normalization."""
import re
import uuid


def _id() -> str:
    return uuid.uuid4().hex[:12]


def norm_name(s: str) -> str:
    """Canonical name key (scenes AND items). The model drifts between 'crypt entrance',
    'crypt_entrance' and stray spacing; if those map to different rows/records, things get
    stranded in unreachable duplicates. One canonical form for every write and lookup."""
    return re.sub(r"[_\s]+", " ", (s or "")).strip()


# Historical name (it started as a scene-key normalizer); kept as an alias so existing
# callers and tests keep working. Prefer norm_name in new code.
norm_location = norm_name
