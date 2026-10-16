#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


def main(params: dict) -> dict:
    body = {
        "name": gd.text_param(params, "name"),
        "mimeType": gd.FOLDER,
        "parents": [gd.text_param(params, "parent_id", required=False) or "root"],
    }
    item = gd.api("POST", "files", params={"fields": gd.FILE_FIELDS}, body=body)
    return gd.entry(item)


if __name__ == "__main__":
    gd.run(main)
