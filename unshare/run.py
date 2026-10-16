#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


def main(params: dict) -> dict:
    item_id = gd.quote_id(params.get("file_id"))
    email = gd.text_param(params, "email", required=False)
    anyone = bool(params.get("anyone"))
    if bool(email) == anyone:
        raise gd.ToolError("Give exactly one of email or anyone.")
    listing = gd.api("GET", f"files/{item_id}/permissions", params={"fields": "permissions(id,type,role,emailAddress)"})
    permissions = listing.get("permissions", [])
    if anyone:
        matches = [item for item in permissions if item.get("type") == "anyone"]
    else:
        matches = [item for item in permissions if (item.get("emailAddress") or "").lower() == email.lower()]
    if not matches:
        raise gd.ToolError("It isn't shared that way. get_metadata lists who it's shared with.")
    if any(item.get("role") == "owner" for item in matches):
        raise gd.ToolError("That's the owner, who can't be removed.")
    for permission in matches:
        gd.api("DELETE", f"files/{item_id}/permissions/{gd.quote_id(permission['id'])}")
    return {"removed": "anyone with the link" if anyone else email}


if __name__ == "__main__":
    gd.run(main)
