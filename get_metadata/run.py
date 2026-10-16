#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


def main(params: dict) -> dict:
    item = gd.get_file(params.get("file_id"), gd.DETAIL_FIELDS)
    out = gd.entry(item)
    out["path"] = gd.path_of(item)
    out["created"] = item.get("createdTime")
    if item.get("description"):
        out["description"] = item["description"]
    out["owned_by_me"] = bool(item.get("ownedByMe"))
    out["owners"] = [owner.get("emailAddress") for owner in item.get("owners") or []]
    if item.get("driveId"):
        out["shared_drive_id"] = item["driveId"]
    out["shared"] = bool(item.get("shared"))
    if "permissions" in item:
        out["sharing"] = [
            {
                "with": permission.get("emailAddress") or permission.get("domain") or permission.get("type"),
                "type": permission.get("type"),
                "role": permission.get("role"),
            }
            for permission in item["permissions"]
        ]
    return out


if __name__ == "__main__":
    gd.run(main)
