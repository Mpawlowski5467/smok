import asyncio
import json
import socket

import httpcore
import pytest

from smok.extensions.review import git, review_diff
from smok.extensions.web import MAX_BYTES, PublicNetwork, Web, url_parts
from smok.tools.files import ToolError, Workspace


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.org/a",
        "http://user:pass@host/a",
        "http://host:0",
        "http://[::1%25lo0]/",
        "http://host/\nheader",
    ],
)
def test_invalid_web_urls(url):
    with pytest.raises(ToolError):
        url_parts(url)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "fc00::1", "224.0.0.1", "0.0.0.0"],
)
async def test_web_blocks_nonpublic_dns(address, monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, 80))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ToolError, match="blocked"):
        await PublicNetwork([]).connect_tcp("rebinding.example", 80)


async def test_web_pins_validated_ip_but_preserves_host_for_tls(monkeypatch):
    calls = []

    async def resolve(*args, **kwargs):
        calls.append("resolve")
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))]

    async def connect(self, host, port, *args):
        calls.append((host, port))
        return "stream"

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    assert await PublicNetwork([]).connect_tcp("example.org", 443) == "stream"
    assert calls == ["resolve", ("93.184.216.34", 443)]


@pytest.fixture
async def web_server():
    async def handle(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        target = request.split(b" ")[1].decode()
        headers = b"Content-Type: text/html; charset=utf-8\r\n"
        status = b"200 OK"
        if target.startswith("/search?"):
            body = json.dumps(
                {
                    "results": [
                        {
                            "title": "Fixture",
                            "url": "https://example.org/source",
                            "content": "Verified snippet",
                        }
                    ]
                }
            ).encode()
            headers = b"Content-Type: application/json\r\n"
        elif target == "/redirect":
            status, body = b"302 Found", b""
            headers = b"Location: http://localhost:1/private\r\n"
        elif target == "/large":
            body = b"a" * (MAX_BYTES + 100)
            headers = b"Content-Type: text/plain\r\n"
        else:
            body = (
                b"<h1>Visible title</h1><script>secret_script()</script>"
                b'<p>Hello world</p><a href="/next">Next</a>'
            )
        writer.write(
            b"HTTP/1.1 "
            + status
            + b"\r\n"
            + headers
            + b"Content-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        try:
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield f"http://127.0.0.1:{port}"


async def test_fetch_real_http_html_search_and_byte_cap(web_server):
    web = Web(
        {
            "web": {
                "allow_hosts": ["127.0.0.1"],
                "search_provider": "searxng",
                "search_url": web_server + "/search",
            }
        }
    )
    page = json.loads(await web.fetch(web_server))
    assert page["source"] == web_server
    assert "Visible title" in page["text"] and "secret_script" not in page["text"]
    assert page["links"] == [web_server + "/next"]
    results = json.loads(await web.search("test & space", 1))
    assert results["results"][0]["url"] == "https://example.org/source"
    large = json.loads(await web.fetch(web_server + "/large"))
    assert len(large["text"]) == MAX_BYTES and large["truncated_at_2_mib"]


async def test_redirect_cannot_bypass_private_host_block(web_server):
    web = Web({"web": {"allow_hosts": ["127.0.0.1"]}})
    with pytest.raises(ToolError, match="blocked"):
        await web.fetch(web_server + "/redirect")


async def test_brave_key_and_no_cross_origin_credential_redirect(monkeypatch):
    web = Web({})
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    with pytest.raises(ToolError, match="BRAVE_SEARCH_API_KEY"):
        await web.search("test")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-secret")

    async def request(url, *, headers=None, redirects=None):
        assert url.startswith("https://api.search.brave.com/res/v1/web/search?")
        assert headers == {"X-Subscription-Token": "test-secret"} and redirects == 0
        return (
            url,
            {},
            b'{"web":{"results":[{"title":"Source","url":"https://example.org","description":"Snippet"}]}}',
            False,
        )

    monkeypatch.setattr(web, "request", request)
    assert "test-secret" not in await web.search("query")


async def repository(root):
    await git(root, "init", "-q")
    await git(root, "config", "user.name", "Smok fixture")
    await git(root, "config", "user.email", "fixture@example.invalid")
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    await git(root, "add", "calc.py")
    await git(root, "commit", "-qm", "baseline")


async def test_review_covers_staged_unstaged_untracked_excludes_metadata(tmp_path):
    await repository(tmp_path)
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / "staged.txt").write_text("staged\n")
    await git(tmp_path, "add", "staged.txt")
    (tmp_path / "new.txt").write_text("untracked\n")
    (tmp_path / ".smok").mkdir()
    (tmp_path / ".smok/private.json").write_text("private session")
    result = json.loads(await review_diff(Workspace(tmp_path)))
    assert set(result["files"]) == {"calc.py", "staged.txt", "new.txt"}
    assert "+    return a - b" in result["patch"] and "+untracked" in result["patch"]
    assert "private session" not in result["patch"]


async def test_branch_review_merge_base_and_external_diff_driver_disabled(tmp_path):
    await repository(tmp_path)
    await git(tmp_path, "branch", "baseline")
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / ".gitattributes").write_text("*.py diff=trap\n")
    await git(tmp_path, "config", "diff.trap.command", "touch should_not_exist")
    await git(tmp_path, "add", ".")
    await git(tmp_path, "commit", "-qm", "regression")
    (tmp_path / "dirty.txt").write_text("uncommitted")
    result = json.loads(await review_diff(Workspace(tmp_path), "baseline"))
    assert "return a - b" in result["patch"] and "dirty.txt" not in result["files"]
    assert not (tmp_path / "should_not_exist").exists()
    with pytest.raises(ToolError, match="Invalid review"):
        await review_diff(Workspace(tmp_path), "--output=/tmp/no")


async def test_review_unborn_repository_and_no_follow_untracked_symlink(tmp_path):
    await git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("first\n")
    await git(tmp_path, "add", "a.txt")
    (tmp_path / "a.txt").write_text("second\n")
    (tmp_path / "link").symlink_to("/etc/passwd")
    result = json.loads(await review_diff(Workspace(tmp_path)))
    assert "+first" in result["patch"] and "+second" in result["patch"]
    assert "root:" not in result["patch"]


async def test_review_bounds_large_untracked_files(tmp_path):
    await git(tmp_path, "init", "-q")
    (tmp_path / "large.txt").write_text("a" * (3 * 1024 * 1024))
    result = json.loads(await review_diff(Workspace(tmp_path)))
    assert result["truncated"] and len(result["patch"]) <= 2 * 1024 * 1024
