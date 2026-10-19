"""Shared Google Drive API client for the plugin's tools."""

import json
import os
import mimetypes
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests

PLUGIN_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PLUGIN_ROOT / "config.json"
# Stavrobot gives each run its own directory; older runners used /tmp/<plugin>.
OUTPUT_DIR = Path(os.environ.get("STAVROBOT_TEMP_DIR", "/tmp/google-drive"))

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://www.googleapis.com/drive/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive"
# Desktop OAuth clients accept a loopback redirect without registering it. Nothing
# listens there: the user copies the URL from the address bar instead.
REDIRECT_URI = "http://127.0.0.1"

# The plugin-runner kills a tool after 30 seconds, so give up a bit earlier
# with a readable error instead.
DEADLINE_SECONDS = 25
TIMEOUT = 15
# The plugin-runner refuses to move more than 25 MB per run.
MAX_TRANSFER_BYTES = 25 * 1024 * 1024
# read returns text, so anything bigger than this is better downloaded.
MAX_READ_BYTES = 5 * 1024 * 1024

FILE_FIELDS = "id,name,mimeType,size,modifiedTime,parents,shortcutDetails,trashed,webViewLink"
DETAIL_FIELDS = (
    f"{FILE_FIELDS},createdTime,description,ownedByMe,owners(emailAddress),shared,driveId,"
    "permissions(id,type,role,emailAddress,domain)"
)

GOOGLE = "application/vnd.google-apps."
FOLDER = GOOGLE + "folder"
SHORTCUT = GOOGLE + "shortcut"
TYPES = {
    FOLDER: "folder",
    GOOGLE + "document": "document",
    GOOGLE + "spreadsheet": "spreadsheet",
    GOOGLE + "presentation": "presentation",
    GOOGLE + "drawing": "drawing",
    GOOGLE + "form": "form",
    SHORTCUT: "shortcut",
}

# Export formats per Google file type, by extension. The first one is the default.
EXPORTS = {
    GOOGLE + "document": {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "odt": "application/vnd.oasis.opendocument.text",
        "md": "text/markdown",
        "txt": "text/plain",
        "html": "text/html",
        "rtf": "application/rtf",
        "epub": "application/epub+zip",
    },
    GOOGLE + "spreadsheet": {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "ods": "application/vnd.oasis.opendocument.spreadsheet",
        "pdf": "application/pdf",
        "csv": "text/csv",
        "tsv": "text/tab-separated-values",
    },
    GOOGLE + "presentation": {
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "odp": "application/vnd.oasis.opendocument.presentation",
        "txt": "text/plain",
    },
    GOOGLE + "drawing": {
        "png": "image/png",
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "svg": "image/svg+xml",
    },
}

# What read exports each Google type to.
READ_EXPORTS = {
    GOOGLE + "document": "text/markdown",
    GOOGLE + "spreadsheet": "text/csv",
    GOOGLE + "presentation": "text/plain",
}

TEXT_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/yaml",
    "application/x-sh",
    "application/sql",
}

# upload with convert: which Google type each source type turns into.
CONVERSIONS = {
    "text/plain": "document",
    "text/markdown": "document",
    "text/html": "document",
    "application/rtf": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.oasis.opendocument.text": "document",
    "text/csv": "spreadsheet",
    "text/tab-separated-values": "spreadsheet",
    "application/vnd.ms-excel": "spreadsheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "spreadsheet",
    "application/vnd.oasis.opendocument.spreadsheet": "spreadsheet",
    "application/vnd.ms-powerpoint": "presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "presentation",
    "application/vnd.oasis.opendocument.presentation": "presentation",
}

mimetypes.add_type("text/markdown", ".md")

_started = time.monotonic()
session = requests.Session()


class ToolError(Exception):
    pass


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except FileNotFoundError:
        return {}
    except ValueError:
        raise ToolError("config.json is not valid JSON.")


def save_config(updates: dict) -> None:
    # Read again right before writing so keys set elsewhere, like permissions, survive.
    config = load_config()
    config.update(updates)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def client_credentials(config: dict) -> tuple[str, str]:
    client_id = str(config.get("client_id") or "").strip()
    client_secret = str(config.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ToolError("Set client_id and client_secret from your Google Cloud OAuth client first.")
    return client_id, client_secret


def send(method: str, url: str, **kwargs) -> requests.Response:
    remaining = DEADLINE_SECONDS - (time.monotonic() - _started)
    if remaining < 1:
        raise ToolError("Ran out of time talking to Google Drive, try a smaller request.")
    try:
        return session.request(method, url, timeout=min(TIMEOUT, remaining), **kwargs)
    except requests.Timeout:
        raise ToolError("Google Drive did not respond in time.")
    except requests.RequestException as error:
        raise ToolError(f"Network error talking to Google Drive ({type(error).__name__}).")


def token_error(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    return body.get("error_description") or body.get("error") or f"HTTP {response.status_code}"


_token = None


def access_token() -> str:
    global _token
    if _token:
        return _token
    config = load_config()
    client_id, client_secret = client_credentials(config)
    refresh_token = str(config.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ToolError("Google Drive is not connected yet. Run auth_url, then auth_complete.")
    response = send(
        "POST",
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    if not response.ok:
        reason = token_error(response)
        hint = ""
        if "invalid_grant" in reason or "expired" in reason.lower():
            hint = (
                " Tokens from an OAuth app in Testing status expire after 7 days, publish the app to production first."
            )
        raise ToolError(f"Google refused the refresh token ({reason}).{hint} Run auth_url and auth_complete again.")
    _token = response.json()["access_token"]
    return _token


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {access_token()}"}


def api_error(response: requests.Response) -> ToolError:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {}
    message = error.get("message") or response.text.strip()[:300]
    reasons = {item.get("reason") for item in error.get("errors") or [] if isinstance(item, dict)}

    if response.status_code == 401:
        return ToolError("Google rejected the access token. Run auth_url and auth_complete again.")
    if response.status_code == 403 and ("insufficientPermissions" in reasons or "scopes" in message.lower()):
        return ToolError(f"The token lacks the {SCOPE} scope. Run auth_url and auth_complete again.")
    if "accessNotConfigured" in reasons or "SERVICE_DISABLED" in message:
        return ToolError("The Google Drive API is off in your Google Cloud project. Enable it, then retry.")
    if response.status_code == 429 or reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
        return ToolError("Google Drive is rate limiting, retry in a minute.")
    if "exportSizeLimitExceeded" in reasons:
        return ToolError("Google only exports files up to 10 MB. Try another format, or open it in Drive.")
    if "storageQuotaExceeded" in reasons:
        return ToolError("The Google Drive storage is full.")
    if response.status_code == 404:
        return ToolError("Not found. Check the id, the file may be gone or not shared with you.")
    return ToolError(f"Google Drive API error {response.status_code}: {message}")


def api(method: str, path: str, params=None, body=None) -> dict:
    response = send(
        method,
        f"{API_URL}/{path}",
        headers=auth_headers(),
        params={"supportsAllDrives": "true", **(params or {})},
        json=body,
    )
    if not response.ok:
        raise api_error(response)
    return response.json() if response.content else {}


def parallel(function, items: list) -> list:
    access_token()  # fetch once before fanning out
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
        return list(pool.map(function, items))


def file_id(value, name: str = "file_id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{name} is required.")
    return value.strip()


def quote_id(value) -> str:
    return quote(file_id(value), safe="")


def get_file(value, fields: str = FILE_FIELDS) -> dict:
    return api("GET", f"files/{quote_id(value)}", params={"fields": fields})


def resolve_shortcut(item: dict) -> dict:
    if item.get("mimeType") != SHORTCUT:
        return item
    target = (item.get("shortcutDetails") or {}).get("targetId")
    if not target:
        raise ToolError(f"{item.get('name')} is a shortcut with no target.")
    return get_file(target)


def query_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def entry(item: dict) -> dict:
    mime = item.get("mimeType") or ""
    out = {
        "id": item.get("id"),
        "name": item.get("name"),
        "type": TYPES.get(mime, "file"),
        "mime_type": mime,
        "size": int(item["size"]) if item.get("size") is not None else None,
        "modified": item.get("modifiedTime"),
        "link": item.get("webViewLink"),
    }
    if mime == SHORTCUT:
        out["shortcut_to"] = (item.get("shortcutDetails") or {}).get("targetId")
    if item.get("trashed"):
        out["trashed"] = True
    return out


def list_files(query: str, max_results: int, order_by: str | None, page_token=None) -> dict:
    params = {
        "q": query,
        "pageSize": max_results,
        "fields": f"nextPageToken,files({FILE_FIELDS})",
        "includeItemsFromAllDrives": "true",
    }
    if order_by:
        params["orderBy"] = order_by
    if page_token:
        if not isinstance(page_token, str):
            raise ToolError("page_token must be a string.")
        params["pageToken"] = page_token
    listing = api("GET", "files", params=params)
    out = {"files": [entry(item) for item in listing.get("files", [])]}
    if listing.get("nextPageToken"):
        out["next_page_token"] = listing["nextPageToken"]
    return out


def path_of(item: dict) -> str | None:
    """Walk up the parents to build a readable path, e.g. My Drive/Work/report.pdf."""
    names = [item.get("name")]
    parents = item.get("parents") or []
    for _ in range(20):
        if not parents:
            break
        try:
            parent = get_file(parents[0], "id,name,parents")
        except ToolError:
            return None  # a parent we can't see, like someone else's folder
        names.append(parent.get("name"))
        parents = parent.get("parents") or []
    return "/".join(reversed(names))


def safe_name(name: str, fallback: str = "file") -> str:
    # Drive allows / in names, so keep the file inside OUTPUT_DIR.
    cleaned = Path(str(name).replace("\\", "/").replace("/", "_")).name.strip()
    return cleaned if cleaned not in ("", ".", "..") else fallback


def download_to_file(response: requests.Response, name: str) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / name
    written = 0
    with target.open("wb") as handle:
        for chunk in response.iter_content(1024 * 1024):
            written += len(chunk)
            if written > MAX_TRANSFER_BYTES:
                handle.close()
                target.unlink()
                raise ToolError("The file is over the 25 MB limit.")
            handle.write(chunk)
    return written


def fetch_bytes(path: str, params: dict, limit: int) -> bytes:
    response = send("GET", f"{API_URL}/{path}", headers=auth_headers(), params=params, stream=True)
    if not response.ok:
        raise api_error(response)
    data = bytearray()
    for chunk in response.iter_content(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            response.close()
            raise ToolError(f"The content is over {limit // 1024 // 1024} MB, use download instead.")
    return bytes(data)


def upload(method: str, path: str, metadata: dict, data: bytes, mime: str, params: dict) -> dict:
    """Resumable upload: one request for the metadata, one for the bytes."""
    start = send(
        method,
        f"{UPLOAD_URL}/{path}",
        headers={
            **auth_headers(),
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": mime,
            "X-Upload-Content-Length": str(len(data)),
        },
        params={"uploadType": "resumable", "supportsAllDrives": "true", **params},
        json=metadata,
    )
    if not start.ok:
        raise api_error(start)
    location = start.headers.get("Location")
    if not location:
        raise ToolError("Google Drive did not return an upload address.")
    response = send("PUT", location, headers={"Content-Type": mime}, data=data)
    if not response.ok:
        raise api_error(response)
    return response.json()


def read_input(value) -> tuple[str, bytes]:
    """Read a file parameter and return its name and bytes."""
    path = Path(value)
    if not path.is_file():
        raise ToolError("file was not found.")
    data = path.read_bytes()
    # The plugin-runner puts input files in OUTPUT_DIR and sends back whatever is
    # left there, so remove the input to keep it from coming back as an output.
    if path.resolve().parent == OUTPUT_DIR.resolve():
        path.unlink()
    return path.name, data


def guess_mime(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def int_param(params: dict, name: str, default: int, low: int, high: int) -> int:
    value = params.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{name} must be a whole number.")
    return max(low, min(high, value))


def text_param(params: dict, name: str, required: bool = True) -> str | None:
    value = params.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ToolError(f"{name} is required.")
        return None
    if not isinstance(value, str):
        raise ToolError(f"{name} must be a string.")
    return value.strip()


def id_list(value, name: str) -> list:
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ToolError(f"{name} must be a list of ids or a comma-separated string.")
    ids = [item.strip() for item in value if item.strip()]
    if not ids:
        raise ToolError(f"{name} is required.")
    if len(ids) > 100:
        raise ToolError(f"At most 100 {name} at once.")
    return ids


def run(main) -> None:
    try:
        raw = sys.stdin.read()
        params = json.loads(raw) if raw.strip() else {}
        if not isinstance(params, dict):
            raise ToolError("Input must be a JSON object.")
        result = main(params)
    except ToolError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print("Input is not valid JSON.", file=sys.stderr)
        sys.exit(1)
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
