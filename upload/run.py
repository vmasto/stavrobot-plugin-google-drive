#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


def main(params: dict) -> dict:
    source, text = params.get("file"), params.get("text")
    if bool(source) == (text is not None):
        raise gd.ToolError("Give exactly one of file or text.")
    name = gd.text_param(params, "name", required=False)
    replace_id = gd.text_param(params, "replace_file_id", required=False)
    if source:
        source_name, data = gd.read_input(source)
        name = name or source_name
        mime = gd.guess_mime(name)
    elif isinstance(text, str):
        if not name and not replace_id:
            raise gd.ToolError("name is required with text.")
        data = text.encode()
        mime = gd.guess_mime(name) if name else "text/plain"
        if mime == "application/octet-stream":
            mime = "text/plain"
    else:
        raise gd.ToolError("text must be a string.")
    if len(data) > gd.MAX_TRANSFER_BYTES:
        raise gd.ToolError("Upload is over the 25 MB limit.")

    fields = {"fields": gd.FILE_FIELDS}
    if replace_id:
        if params.get("folder_id") or params.get("convert"):
            raise gd.ToolError("folder_id and convert don't apply with replace_file_id.")
        metadata = {"name": name} if name and params.get("name") else {}
        item = gd.upload("PATCH", f"files/{gd.quote_id(replace_id)}", metadata, data, mime, fields)
    else:
        metadata = {"name": name, "parents": [gd.text_param(params, "folder_id", required=False) or "root"]}
        if params.get("convert"):
            target = gd.CONVERSIONS.get(mime)
            if not target:
                raise gd.ToolError(f"Drive can't convert {mime} files to a Google file.")
            metadata["mimeType"] = gd.GOOGLE + target
            # Drive keeps the name as given, so notes.md would become a Doc called notes.md.
            metadata["name"] = Path(name).stem or name
        item = gd.upload("POST", "files", metadata, data, mime, fields)
    return gd.entry(item)


if __name__ == "__main__":
    gd.run(main)
