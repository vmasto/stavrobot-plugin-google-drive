#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


FORMATS = {"text/markdown": "markdown", "text/csv": "csv", "text/plain": "text"}


def main(params: dict) -> dict:
    item = gd.resolve_shortcut(gd.get_file(params.get("file_id")))
    mime = item.get("mimeType") or ""
    item_id = gd.quote_id(item["id"])
    if mime in gd.READ_EXPORTS:
        export = gd.READ_EXPORTS[mime]
        data = gd.fetch_bytes(f"files/{item_id}/export", {"mimeType": export}, gd.MAX_READ_BYTES)
        text_format = FORMATS[export]
    elif mime.startswith("text/") or mime in gd.TEXT_TYPES or mime.endswith(("+json", "+xml")):
        if int(item.get("size") or 0) > gd.MAX_READ_BYTES:
            raise gd.ToolError(f"{item['name']} is over 5 MB, use download instead.")
        data = gd.fetch_bytes(f"files/{item_id}", {"alt": "media", "supportsAllDrives": "true"}, gd.MAX_READ_BYTES)
        text_format = "text"
    else:
        kind = gd.TYPES.get(mime, mime or "file")
        raise gd.ToolError(f"{item['name']} is a {kind}, which read can't show as text. Use download.")

    text = data.decode("utf-8-sig", errors="replace")
    max_chars = gd.int_param(params, "max_chars", 20000, 500, 100000)
    out = {"id": item["id"], "name": item["name"], "format": text_format, "content": text[:max_chars]}
    if len(text) > max_chars:
        out["truncated"] = True
        out["length"] = len(text)
    return out


if __name__ == "__main__":
    gd.run(main)
