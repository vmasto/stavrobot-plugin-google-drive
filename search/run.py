#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


TYPE_CLAUSES = {
    "folder": f"mimeType = '{gd.FOLDER}'",
    "document": f"mimeType = '{gd.GOOGLE}document'",
    "spreadsheet": f"mimeType = '{gd.GOOGLE}spreadsheet'",
    "presentation": f"mimeType = '{gd.GOOGLE}presentation'",
    "pdf": "mimeType = 'application/pdf'",
    "image": "mimeType contains 'image/'",
    "video": "mimeType contains 'video/'",
    "audio": "mimeType contains 'audio/'",
}


def main(params: dict) -> dict:
    clauses = ["trashed = false"]
    text = gd.text_param(params, "text", required=False)
    if text:
        quoted = gd.query_string(text)
        clauses.append(f"(name contains {quoted} or fullText contains {quoted})")
    kind = gd.text_param(params, "type", required=False)
    if kind:
        if kind.lower() not in TYPE_CLAUSES:
            raise gd.ToolError(f"type must be one of: {', '.join(TYPE_CLAUSES)}.")
        clauses.append(TYPE_CLAUSES[kind.lower()])
    folder_id = gd.text_param(params, "folder_id", required=False)
    if folder_id:
        clauses.append(f"{gd.query_string(folder_id)} in parents")
    if params.get("shared_with_me"):
        clauses.append("sharedWithMe")
    raw = gd.text_param(params, "query", required=False)
    if raw:
        clauses.append(f"({raw})")
    query = " and ".join(clauses)
    # Drive refuses orderBy on full-text searches and sorts those by relevance.
    order_by = None if "fullText" in query else "modifiedTime desc"
    listing = gd.list_files(query, gd.int_param(params, "max_results", 20, 1, 50), order_by, params.get("page_token"))
    return {"query": query, **listing}


if __name__ == "__main__":
    gd.run(main)
