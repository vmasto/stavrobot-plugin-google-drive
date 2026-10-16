#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


def main(params: dict) -> dict:
    item = gd.get_file(params.get("file_id"))
    if item.get("mimeType") == gd.FOLDER:
        raise gd.ToolError("Drive can't copy folders.")
    body = {}
    name = gd.text_param(params, "name", required=False)
    if name:
        body["name"] = name
    folder_id = gd.text_param(params, "folder_id", required=False)
    if folder_id:
        body["parents"] = [folder_id]
    copied = gd.api("POST", f"files/{gd.quote_id(item['id'])}/copy", params={"fields": gd.FILE_FIELDS}, body=body)
    return gd.entry(copied)


if __name__ == "__main__":
    gd.run(main)
