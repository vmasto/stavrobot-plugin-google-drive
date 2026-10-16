"""Offline tests against a fake Google Drive.

Run with: uv run --with pytest --with requests pytest tests
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import drive_client as gd  # noqa: E402

DOC = gd.GOOGLE + "document"
SHEET = gd.GOOGLE + "spreadsheet"


class Response:
    def __init__(self, status=200, body=None, raw=None, headers=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.content = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
        self.text = self.content.decode(errors="replace")
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def iter_content(self, size):
        for start in range(0, len(self.content), size):
            yield self.content[start : start + size]

    def close(self):
        pass


def item(file_id="f1", name="Notes", mime="text/plain", **extra):
    return {"id": file_id, "name": name, "mimeType": mime, "parents": ["root"], **extra}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"client_id": "cid", "client_secret": "sec", "refresh_token": "rt", "permissions": ["*"]})
    )
    monkeypatch.setattr(gd, "CONFIG_PATH", config)
    monkeypatch.setattr(gd, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(gd, "_token", None)

    calls, routes = [], {}

    def request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        assert 0 < kwargs["timeout"] <= gd.TIMEOUT
        if url == gd.TOKEN_URL:
            if kwargs["data"]["grant_type"] == "refresh_token":
                return Response(200, {"access_token": "at"})
            return routes[("POST", "token")]
        path = url.removeprefix(gd.API_URL + "/").removeprefix(gd.UPLOAD_URL + "/")
        handler = routes[(method, path)]
        return handler(kwargs) if callable(handler) else handler

    monkeypatch.setattr(gd.session, "request", request)
    return type("Fake", (), {"routes": routes, "calls": calls, "config": config})


def tool(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}", ROOT / name / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def last(fake, method, path):
    return [call for call in fake.calls if call["method"] == method and call["url"].endswith(path)][-1]


def test_auth_url_requests_offline_drive_scope(fake):
    url = tool("auth_url")({})["url"]
    for part in ("client_id=cid", "access_type=offline", "prompt=consent", "auth%2Fdrive&", "127.0.0.1"):
        assert part in url


def test_auth_complete_saves_token_and_keeps_permissions(fake):
    fake.routes[("POST", "token")] = Response(200, {"refresh_token": "new", "access_token": "fresh", "scope": gd.SCOPE})
    fake.routes[("GET", "about")] = Response(200, {"user": {"emailAddress": "me@gmail.com"}})
    out = tool("auth_complete")({"url": "http://127.0.0.1/?code=4/abc&scope=" + gd.SCOPE})
    assert out == {"connected": True, "email": "me@gmail.com"}
    assert fake.calls[0]["data"]["code"] == "4/abc"
    saved = json.loads(fake.config.read_text())
    assert saved["refresh_token"] == "new" and saved["permissions"] == ["*"]

    fake.routes[("POST", "token")] = Response(200, {"refresh_token": "x", "access_token": "x", "scope": "openid"})
    with pytest.raises(gd.ToolError, match="not granted"):
        tool("auth_complete")({"url": "abc"})


def test_expired_refresh_token_explains_testing_mode(fake, monkeypatch):
    monkeypatch.setattr(gd.session, "request", lambda *args, **kwargs: Response(400, {"error": "invalid_grant"}))
    with pytest.raises(gd.ToolError, match="7 days"):
        tool("list_folder")({})


def test_list_folder_lists_children_folders_first(fake):
    fake.routes[("GET", "files/root")] = Response(200, {"id": "0Aroot", "name": "My Drive", "mimeType": gd.FOLDER})
    fake.routes[("GET", "files")] = Response(
        200,
        {
            "files": [
                item("d1", "Work", gd.FOLDER),
                item("f1", "a.pdf", "application/pdf", size="2048", webViewLink="https://drive.google.com/f1"),
            ],
            "nextPageToken": "p2",
        },
    )
    out = tool("list_folder")({})
    assert out["folder"] == {"id": "0Aroot", "name": "My Drive"} and out["next_page_token"] == "p2"
    assert [(f["name"], f["type"], f["size"]) for f in out["files"]] == [
        ("Work", "folder", None),
        ("a.pdf", "file", 2048),
    ]
    assert out["files"][1]["link"] == "https://drive.google.com/f1"
    assert "webViewLink" in last(fake, "GET", "files")["params"]["fields"]
    params = last(fake, "GET", "files")["params"]
    assert params["q"] == "'0Aroot' in parents and trashed = false" and params["orderBy"] == "folder,name_natural"


def test_list_folder_rejects_a_file(fake):
    fake.routes[("GET", "files/f1")] = Response(200, item())
    with pytest.raises(gd.ToolError, match="not a folder"):
        tool("list_folder")({"folder_id": "f1"})


def test_search_builds_the_query_and_escapes_quotes(fake):
    fake.routes[("GET", "files")] = Response(200, {"files": []})
    out = tool("search")({"text": "Anna's \\ report", "type": "PDF", "shared_with_me": True})
    expected = (
        "trashed = false and (name contains 'Anna\\'s \\\\ report' or fullText contains 'Anna\\'s \\\\ report') "
        "and mimeType = 'application/pdf' and sharedWithMe"
    )
    assert out["query"] == expected
    assert "orderBy" not in last(fake, "GET", "files")["params"]

    tool("search")({"query": "modifiedTime > '2026-01-01'"})
    params = last(fake, "GET", "files")["params"]
    assert params["q"] == "trashed = false and (modifiedTime > '2026-01-01')"
    assert params["orderBy"] == "modifiedTime desc"

    with pytest.raises(gd.ToolError, match="type must be"):
        tool("search")({"type": "spreadsheets"})


def test_get_metadata_builds_path_and_sharing(fake):
    fake.routes[("GET", "files/f1")] = Response(
        200,
        item(
            parents=["d1"],
            webViewLink="https://drive.google.com/f1",
            ownedByMe=True,
            owners=[{"emailAddress": "me@gmail.com"}],
            shared=True,
            permissions=[
                {"id": "p1", "type": "user", "role": "owner", "emailAddress": "me@gmail.com"},
                {"id": "anyoneWithLink", "type": "anyone", "role": "reader"},
            ],
        ),
    )
    fake.routes[("GET", "files/d1")] = Response(200, {"id": "d1", "name": "Work", "parents": ["0Aroot"]})
    fake.routes[("GET", "files/0Aroot")] = Response(200, {"id": "0Aroot", "name": "My Drive"})
    out = tool("get_metadata")({"file_id": "f1"})
    assert out["path"] == "My Drive/Work/Notes" and out["link"] == "https://drive.google.com/f1"
    assert out["sharing"] == [
        {"with": "me@gmail.com", "type": "user", "role": "owner"},
        {"with": "anyone", "type": "anyone", "role": "reader"},
    ]


def test_read_exports_docs_as_markdown_and_truncates(fake):
    fake.routes[("GET", "files/doc1")] = Response(200, item("doc1", "Plan", DOC))
    fake.routes[("GET", "files/doc1/export")] = Response(200, raw=("# Σχέδιο\n" + "a" * 900).encode())
    out = tool("read")({"file_id": "doc1", "max_chars": 500})
    assert out["format"] == "markdown" and out["content"].startswith("# Σχέδιο")
    assert out["truncated"] and len(out["content"]) == 500
    assert last(fake, "GET", "doc1/export")["params"] == {"mimeType": "text/markdown"}


def test_read_follows_shortcuts_and_reads_text_files(fake):
    fake.routes[("GET", "files/s1")] = Response(
        200, item("s1", "notes", gd.SHORTCUT, shortcutDetails={"targetId": "f1"})
    )
    fake.routes[("GET", "files/f1")] = lambda kwargs: (
        Response(200, raw=b"\xef\xbb\xbfhello") if kwargs["params"].get("alt") else Response(200, item(size="8"))
    )
    out = tool("read")({"file_id": "s1"})
    assert out == {"id": "f1", "name": "Notes", "format": "text", "content": "hello"}


def test_read_refuses_binary_files(fake):
    fake.routes[("GET", "files/f1")] = Response(200, item(mime="application/pdf"))
    with pytest.raises(gd.ToolError, match="Use download"):
        tool("read")({"file_id": "f1"})


def test_download_exports_sheet_and_adds_extension(fake):
    fake.routes[("GET", "files/sh1")] = Response(200, item("sh1", "Budget/2026", SHEET))
    fake.routes[("GET", "files/sh1/export")] = Response(200, raw=b"a,b\n")
    out = tool("download")({"file_id": "sh1", "format": ".CSV"})
    assert out["file"] == "Budget_2026.csv" and out["mime_type"] == "text/csv" and out["size"] == 4
    assert (gd.OUTPUT_DIR / "Budget_2026.csv").read_bytes() == b"a,b\n"

    tool("download")({"file_id": "sh1"})
    assert last(fake, "GET", "sh1/export")["params"]["mimeType"].endswith("spreadsheetml.sheet")
    with pytest.raises(gd.ToolError, match="format must be one of"):
        tool("download")({"file_id": "sh1", "format": "docx"})


def test_download_binary_checks_size(fake):
    fake.routes[("GET", "files/f1")] = lambda kwargs: (
        Response(200, raw=b"%PDF")
        if kwargs["params"].get("alt")
        else Response(200, item(name="../a.pdf", mime="application/pdf", size="4"))
    )
    assert tool("download")({"file_id": "f1"})["file"] == ".._a.pdf"
    fake.routes[("GET", "files/f1")] = Response(200, item(size=str(30 * 1024 * 1024)))
    with pytest.raises(gd.ToolError, match="25 MB"):
        tool("download")({"file_id": "f1"})


def upload_routes(fake, method, path):
    fake.routes[(method, path)] = Response(200, headers={"Location": "https://upload.example/session"})
    fake.routes[("PUT", "https://upload.example/session")] = Response(
        200, item("new", "notes.md", DOC, webViewLink="https://docs.google.com/new")
    )


def test_upload_text_converts_markdown_to_a_doc(fake):
    upload_routes(fake, "POST", "files")
    out = tool("upload")({"text": "# Hi", "name": "notes.md", "folder_id": "d1", "convert": True})
    assert out["id"] == "new" and out["type"] == "document" and out["link"] == "https://docs.google.com/new"
    start = last(fake, "POST", "files")
    assert start["json"] == {"name": "notes", "parents": ["d1"], "mimeType": DOC}
    assert start["headers"]["X-Upload-Content-Type"] == "text/markdown"
    assert start["params"]["uploadType"] == "resumable"
    assert last(fake, "PUT", "session")["data"] == b"# Hi"


def test_upload_file_and_replace(fake, tmp_path):
    upload_routes(fake, "POST", "files")
    # The plugin-runner puts input files in OUTPUT_DIR, so the tool must remove them.
    gd.OUTPUT_DIR.mkdir()
    source = gd.OUTPUT_DIR / "photo.jpg"
    source.write_bytes(b"jpg")
    tool("upload")({"file": str(source)})
    assert not source.exists()
    source.write_bytes(b"jpg")
    start = last(fake, "POST", "files")
    assert start["json"] == {"name": "photo.jpg", "parents": ["root"]}
    assert start["headers"]["X-Upload-Content-Type"] == "image/jpeg"

    upload_routes(fake, "PATCH", "files/f1")
    tool("upload")({"text": "v2", "replace_file_id": "f1"})
    assert last(fake, "PATCH", "files/f1")["json"] == {}

    with pytest.raises(gd.ToolError, match="exactly one"):
        tool("upload")({"text": "x", "file": str(source), "name": "a"})
    with pytest.raises(gd.ToolError, match="name is required"):
        tool("upload")({"text": "x"})
    with pytest.raises(gd.ToolError, match="can't convert"):
        tool("upload")({"file": str(source), "convert": True})


def test_move_swaps_parents_and_renames(fake):
    fake.routes[("GET", "files/f1")] = Response(200, item(parents=["old"]))
    fake.routes[("PATCH", "files/f1")] = Response(200, item(name="Renamed", parents=["d2"]))
    out = tool("move")({"file_id": "f1", "folder_id": "d2", "name": "Renamed"})
    assert out["name"] == "Renamed"
    call = last(fake, "PATCH", "files/f1")
    assert call["params"]["addParents"] == "d2" and call["params"]["removeParents"] == "old"
    assert call["json"] == {"name": "Renamed"}


def test_copy_refuses_folders(fake):
    fake.routes[("GET", "files/d1")] = Response(200, item("d1", "Work", gd.FOLDER))
    with pytest.raises(gd.ToolError, match="can't copy folders"):
        tool("copy")({"file_id": "d1"})


def test_trash_and_restore(fake):
    fake.routes[("PATCH", "files/f1")] = lambda kwargs: Response(200, {"id": "f1", "name": "Notes"})
    fake.routes[("PATCH", "files/f2")] = lambda kwargs: Response(200, {"id": "f2", "name": "Old"})
    assert tool("trash")({"file_ids": "f1, f2"}) == {"trashed": ["Notes", "Old"]}
    assert last(fake, "PATCH", "files/f2")["json"] == {"trashed": True}
    assert tool("trash")({"file_ids": ["f1"], "restore": True}) == {"restored": ["Notes"]}
    assert last(fake, "PATCH", "files/f1")["json"] == {"trashed": False}


def test_share_with_a_person_and_with_a_link(fake):
    fake.routes[("GET", "files/f1")] = Response(200, item(webViewLink="https://drive.google.com/f1"))
    fake.routes[("POST", "files/f1/permissions")] = lambda kwargs: Response(
        200,
        {
            "id": "p9",
            "role": kwargs["json"]["role"],
            **({"emailAddress": "anna@x.com"} if "emailAddress" in kwargs["json"] else {}),
        },
    )
    out = tool("share")({"file_id": "f1", "email": "anna@x.com", "role": "Writer", "message": "Για σένα"})
    assert out == {"shared": "Notes", "with": "anna@x.com", "role": "writer", "link": "https://drive.google.com/f1"}
    call = last(fake, "POST", "permissions")
    assert call["json"] == {"type": "user", "role": "writer", "emailAddress": "anna@x.com"}
    assert call["params"]["sendNotificationEmail"] == "true" and call["params"]["emailMessage"] == "Για σένα"

    out = tool("share")({"file_id": "f1", "anyone": True})
    assert out["with"] == "anyone with the link"
    call = last(fake, "POST", "permissions")
    assert call["json"] == {"type": "anyone", "role": "reader", "allowFileDiscovery": False}
    assert "sendNotificationEmail" not in call["params"]

    with pytest.raises(gd.ToolError, match="exactly one"):
        tool("share")({"file_id": "f1"})
    with pytest.raises(gd.ToolError, match="role must be"):
        tool("share")({"file_id": "f1", "email": "a@x.com", "role": "owner"})


def test_unshare(fake):
    fake.routes[("GET", "files/f1/permissions")] = Response(
        200,
        {
            "permissions": [
                {"id": "p1", "type": "user", "role": "owner", "emailAddress": "me@gmail.com"},
                {"id": "p2", "type": "user", "role": "reader", "emailAddress": "Anna@x.com"},
                {"id": "anyoneWithLink", "type": "anyone", "role": "reader"},
            ]
        },
    )
    fake.routes[("DELETE", "files/f1/permissions/p2")] = Response(204)
    fake.routes[("DELETE", "files/f1/permissions/anyoneWithLink")] = Response(204)
    assert tool("unshare")({"file_id": "f1", "email": "anna@x.com"}) == {"removed": "anna@x.com"}
    assert tool("unshare")({"file_id": "f1", "anyone": True}) == {"removed": "anyone with the link"}
    with pytest.raises(gd.ToolError, match="owner"):
        tool("unshare")({"file_id": "f1", "email": "me@gmail.com"})
    with pytest.raises(gd.ToolError, match="isn't shared"):
        tool("unshare")({"file_id": "f1", "email": "bob@x.com"})


def test_api_errors_explain_the_fix(fake):
    def error(status, reason, message):
        return Response(status, {"error": {"code": status, "message": message, "errors": [{"reason": reason}]}})

    fake.routes[("GET", "files/f1")] = error(
        403, "insufficientPermissions", "Request had insufficient authentication scopes."
    )
    with pytest.raises(gd.ToolError, match="auth/drive scope"):
        tool("get_metadata")({"file_id": "f1"})
    fake.routes[("GET", "files/f1")] = error(403, "accessNotConfigured", "Google Drive API has not been used")
    with pytest.raises(gd.ToolError, match="Enable it"):
        tool("get_metadata")({"file_id": "f1"})
    fake.routes[("GET", "files/f1")] = error(404, "notFound", "File not found: f1.")
    with pytest.raises(gd.ToolError, match="Not found"):
        tool("get_metadata")({"file_id": "f1"})


def test_errors_exit_non_zero_with_stderr(tmp_path):
    # No config.json next to the copied tool, so it must fail before any network call.
    plugin = tmp_path / "google-drive"
    (plugin / "search").mkdir(parents=True)
    (plugin / "drive_client.py").write_text((ROOT / "drive_client.py").read_text())
    (plugin / "search" / "run.py").write_text((ROOT / "search" / "run.py").read_text())
    result = subprocess.run(
        [sys.executable, str(plugin / "search" / "run.py")],
        input="{}",
        capture_output=True,
        text=True,
        cwd=plugin / "search",
    )
    assert result.returncode == 1 and result.stdout == ""
    assert "client_id" in result.stderr


def test_run_scripts_are_executable_in_git():
    output = subprocess.run(
        ["git", "ls-files", "-s", "--", "*/run.py"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    entries = [line.split(maxsplit=3) for line in output.splitlines()]
    if not entries:
        pytest.skip("run.py files are not in the git index yet")
    assert all(mode == "100755" for mode, *_ in entries), entries
