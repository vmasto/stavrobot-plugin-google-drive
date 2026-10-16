#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


def main(params: dict) -> dict:
    item = gd.resolve_shortcut(gd.get_file(params.get("file_id")))
    mime = item.get("mimeType") or ""
    item_id = gd.quote_id(item["id"])
    requested = (gd.text_param(params, "format", required=False) or "").lower().lstrip(".")
    name = gd.safe_name(item["name"])

    if mime.startswith(gd.GOOGLE):
        exports = gd.EXPORTS.get(mime)
        if not exports:
            kind = gd.TYPES.get(mime, mime)
            raise gd.ToolError(f"{item['name']} is a {kind}, which Drive can't download.")
        extension = requested or next(iter(exports))
        if extension not in exports:
            raise gd.ToolError(f"format must be one of: {', '.join(exports)}.")
        mime = exports[extension]
        if not name.lower().endswith(f".{extension}"):
            name = f"{name}.{extension}"
        url, query = f"{gd.API_URL}/files/{item_id}/export", {"mimeType": mime}
    else:
        if requested:
            raise gd.ToolError("format only applies to Google Docs, Sheets, Slides and Drawings.")
        if int(item.get("size") or 0) > gd.MAX_TRANSFER_BYTES:
            size_mb = int(item["size"]) / 1024 / 1024
            raise gd.ToolError(f"{item['name']} is {size_mb:.0f} MB, over the 25 MB limit.")
        url, query = f"{gd.API_URL}/files/{item_id}", {"alt": "media", "supportsAllDrives": "true"}

    response = gd.send("GET", url, headers=gd.auth_headers(), params=query, stream=True)
    if not response.ok:
        raise gd.api_error(response)
    size = gd.download_to_file(response, name)
    return {"file": name, "id": item["id"], "mime_type": mime, "size": size}


if __name__ == "__main__":
    gd.run(main)
