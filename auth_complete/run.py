#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import drive_client as gd  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402


def main(params: dict) -> dict:
    value = gd.text_param(params, "url")
    if value.startswith("http"):
        query = parse_qs(urlparse(value).query)
        if "error" in query:
            raise gd.ToolError(f"Google returned an error: {query['error'][0]}. Run auth_url again.")
        if "code" not in query:
            raise gd.ToolError("That address has no code in it. Copy the full address after allowing access.")
        code = query["code"][0]
    else:
        code = value

    client_id, client_secret = gd.client_credentials(gd.load_config())
    response = gd.send(
        "POST",
        gd.TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": gd.REDIRECT_URI,
        },
    )
    if not response.ok:
        raise gd.ToolError(
            f"Google refused the code ({gd.token_error(response)}). Codes work once and expire fast, run auth_url again."
        )
    body = response.json()
    if gd.SCOPE not in body.get("scope", "").split():
        raise gd.ToolError("Access to Drive was not granted. Run auth_url again and tick the Drive permission.")
    if not body.get("refresh_token"):
        raise gd.ToolError("Google returned no refresh token, run auth_url again.")
    gd.save_config({"refresh_token": body["refresh_token"]})
    gd._token = body["access_token"]
    user = gd.api("GET", "about", params={"fields": "user(emailAddress)"}).get("user") or {}
    return {"connected": True, "email": user.get("emailAddress")}


if __name__ == "__main__":
    gd.run(main)
