"""Offline Blob credential checks; never include credential values in errors."""
import re


def blob_store_identity(store_id: str, token: str) -> str | None:
    """Accept CLI store_<id> or hostname id, bound to the static server token."""
    identifier = store_id.removeprefix("store_")
    if not re.fullmatch(r"[A-Za-z0-9]{1,63}", identifier):
        return None
    match = re.fullmatch(r"vercel_blob_rw_([A-Za-z0-9]{1,63})_([A-Za-z0-9_-]{16,})", token)
    if match is None or match.group(1).lower() != identifier.lower():
        return None
    return identifier.lower()
