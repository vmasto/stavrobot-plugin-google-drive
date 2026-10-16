#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


def main(params: dict) -> dict:
    ids = gd.id_list(params.get("file_ids"), "file_ids")
    trashed = not params.get("restore")

    def update(item_id):
        return gd.api("PATCH", f"files/{gd.quote_id(item_id)}", params={"fields": "id,name"}, body={"trashed": trashed})

    names = [item.get("name") for item in gd.parallel(update, ids)]
    return {"restored" if not trashed else "trashed": names}


if __name__ == "__main__":
    gd.run(main)
