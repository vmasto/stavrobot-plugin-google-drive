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
    folder_id = gd.text_param(params, "folder_id", required=False)
    name = gd.text_param(params, "name", required=False)
    if not folder_id and not name:
        raise gd.ToolError("Give folder_id, name, or both.")
    query = {"fields": gd.FILE_FIELDS}
    if folder_id:
        query["addParents"] = folder_id
        query["removeParents"] = ",".join(item.get("parents") or [])
    updated = gd.api("PATCH", f"files/{gd.quote_id(item['id'])}", params=query, body={"name": name} if name else {})
    return gd.entry(updated)


if __name__ == "__main__":
    gd.run(main)
