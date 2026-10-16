#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


def main(params: dict) -> dict:
    folder = gd.get_file(gd.text_param(params, "folder_id", required=False) or "root", "id,name,mimeType")
    if folder.get("mimeType") != gd.FOLDER:
        raise gd.ToolError(f"{folder.get('name')} is not a folder.")
    listing = gd.list_files(
        f"{gd.query_string(folder['id'])} in parents and trashed = false",
        gd.int_param(params, "max_results", 50, 1, 100),
        "folder,name_natural",
        params.get("page_token"),
    )
    return {"folder": {"id": folder["id"], "name": folder.get("name")}, **listing}


if __name__ == "__main__":
    gd.run(main)
