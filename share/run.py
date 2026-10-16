#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402


ROLES = ("reader", "commenter", "writer")


def main(params: dict) -> dict:
    item = gd.get_file(params.get("file_id"), "id,name,webViewLink")
    email = gd.text_param(params, "email", required=False)
    anyone = bool(params.get("anyone"))
    if bool(email) == anyone:
        raise gd.ToolError("Give exactly one of email or anyone.")
    role = (gd.text_param(params, "role", required=False) or "reader").lower()
    if role not in ROLES:
        raise gd.ToolError(f"role must be one of: {', '.join(ROLES)}.")

    query = {"fields": "id,type,role,emailAddress"}
    if anyone:
        if params.get("message"):
            raise gd.ToolError("message only applies when sharing with an email.")
        body = {"type": "anyone", "role": role, "allowFileDiscovery": False}
    else:
        body = {"type": "user", "role": role, "emailAddress": email}
        notify = params.get("notify", True) is not False
        query["sendNotificationEmail"] = "true" if notify else "false"
        message = gd.text_param(params, "message", required=False)
        if message:
            if not notify:
                raise gd.ToolError("message needs notify on.")
            query["emailMessage"] = message
    permission = gd.api("POST", f"files/{gd.quote_id(item['id'])}/permissions", params=query, body=body)
    return {
        "shared": item["name"],
        "with": "anyone with the link" if anyone else permission.get("emailAddress", email),
        "role": permission.get("role"),
        "link": item.get("webViewLink"),
    }


if __name__ == "__main__":
    gd.run(main)
