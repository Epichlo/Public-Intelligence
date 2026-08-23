"""When gh cannot look, the REST fallback must look honestly or say exactly why.

RECORDED DEFECT this file pins shut: `scripts/generate_status.py` reported a bare
UNVERIFIABLE whenever gh was absent or unauthenticated. That single word masked a
real red CI run for EIGHT DAYS across the v1.0.0 release -- "we could not look"
scanned as "nothing is wrong", which is the exact failure this repo's reporting
culture exists to prevent.

The fix under test: a second, independent way to look (GitHub REST API over
stdlib urllib, no new dependencies), with gh kept primary whenever it works.

Three states must never be conflated:
  (a) looked and green        -> PASS
  (b) looked and red/failing  -> FAIL
  (c) could not look          -> UNVERIFIABLE carrying the concrete reason

Every network-touching test monkeypatches `_http_get`, the module's single
transport seam, so these run offline and deterministically.
"""

from __future__ import annotations

import email.message
import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

HEAD = "c" * 40
OLDER = "d" * 40
HTTPS_URL = "https://github.com/example/public-intelligence.git"
SSH_URL = "git@github.com:example/public-intelligence.git"


def _load_generator() -> Any:
    """Load scripts/generate_status.py as a module (stdlib-only script)."""
    path = REPO_ROOT / "scripts" / "generate_status.py"
    spec = importlib.util.spec_from_file_location("generate_status_rest_fallback", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


generate_status = _load_generator()


def _fake_run(
    remote_url: str | None = HTTPS_URL,
    behind: str = "9",
    gh_output: tuple[int, str] | None = None,
    remote_listing: str | None = None,
):
    """Stand in for the module's `run()` shell helper."""

    def _run(cmd: list[str], **kwargs: Any) -> tuple[int, str]:
        if cmd[:4] == ["git", "remote", "get-url", "origin"]:
            if remote_url is None:
                return 128, "error: No such remote 'origin'"
            return 0, remote_url
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, HEAD
        if cmd[:3] == ["git", "rev-list", "--count"]:
            return 0, behind
        if cmd[:3] == ["gh", "run", "list"]:
            assert gh_output is not None, "gh path must not be reached in this test"
            return gh_output
        if cmd[:2] == ["git", "remote"]:
            listing = remote_listing
            if listing is None:
                listing = f"origin\t{remote_url} (fetch)" if remote_url else ""
            return 0, listing
        return 0, ""

    return _run


def _rest_body(conclusion: str, sha: str = HEAD) -> str:
    """A GitHub actions/runs payload shaped like the real API's."""
    return json.dumps(
        {"total_count": 1, "workflow_runs": [{"head_sha": sha, "conclusion": conclusion}]}
    )


def _patch_rest(monkeypatch: pytest.MonkeyPatch, status: int, body: str) -> list[tuple]:
    calls: list[tuple] = []

    def fake_http_get(url: str, headers: dict[str, str]) -> tuple[int, str]:
        calls.append((url, headers))
        return status, body

    monkeypatch.setattr(generate_status, "_http_get", fake_http_get)
    return calls


def _gh_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generate_status.shutil, "which", lambda _: None)


def _gh_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generate_status.shutil, "which", lambda _: "/usr/bin/gh")


# ---------------------------------------------------------------------------
# The fallback works: it looks and reports what it saw.
# ---------------------------------------------------------------------------


def test_fallback_reports_green_when_gh_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """State (a) through the fallback channel: looked, green, PASS."""
    _gh_absent(monkeypatch)
    monkeypatch.setattr(generate_status, "run", _fake_run())
    calls = _patch_rest(monkeypatch, 200, _rest_body("success"))

    status, reason = generate_status.ci_signal()

    assert status == "PASS"
    assert HEAD[:8] in reason
    # It must have asked about THIS repo, not some guessed slug.
    url, _headers = calls[0]
    assert "/repos/example/public-intelligence/actions/runs" in url


def test_fallback_reports_red_when_the_api_sees_a_failed_head_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State (b): a red run reads as FAIL even when only the API can see it."""
    _gh_absent(monkeypatch)
    monkeypatch.setattr(generate_status, "run", _fake_run())
    _patch_rest(monkeypatch, 200, _rest_body("failure"))

    status, reason = generate_status.ci_signal()

    assert status == "FAIL"
    assert "failure" in reason


def test_fallback_derives_the_slug_from_an_ssh_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    _gh_absent(monkeypatch)
    monkeypatch.setattr(generate_status, "run", _fake_run(remote_url=SSH_URL))
    calls = _patch_rest(monkeypatch, 200, _rest_body("success"))

    status, _reason = generate_status.ci_signal()

    assert status == "PASS"
    url, _headers = calls[0]
    assert "/repos/example/public-intelligence/" in url


def test_fallback_unverified_when_no_run_matches_head(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful look that finds no run for HEAD stays UNVERIFIED, not PASS.

    Same semantics as the gh channel: CI has said nothing about this commit, and
    inventing an answer either way would be the original sin this script guards.
    """
    _gh_absent(monkeypatch)
    monkeypatch.setattr(generate_status, "run", _fake_run())
    _patch_rest(monkeypatch, 200, _rest_body("success", sha=OLDER))

    status, reason = generate_status.ci_signal()

    assert status == "UNVERIFIED"
    assert "never run for HEAD" in reason
    assert "9 commit(s) behind" in reason


def test_token_header_is_sent_when_the_environment_provides_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _gh_absent(monkeypatch)
    monkeypatch.setenv("GH_TOKEN", "tok-secret-123")
    monkeypatch.setattr(generate_status, "run", _fake_run())
    calls = _patch_rest(monkeypatch, 200, _rest_body("success"))

    _status, reason = generate_status.ci_signal()

    _, headers = calls[0]
    assert headers["Authorization"] == "Bearer tok-secret-123"
    assert headers["Authorization"] == "Bearer tok-secret-123"
    # And the credential must never leak into what STATUS.md would render.
    assert "tok-secret-123" not in reason


def test_no_token_header_without_an_environment_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _gh_absent(monkeypatch)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(generate_status, "run", _fake_run())
    calls = _patch_rest(monkeypatch, 200, _rest_body("success"))

    generate_status.ci_signal()

    _, headers = calls[0]
    assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# The fallback fails honestly: could-not-look always names its cause.
# ---------------------------------------------------------------------------


def test_transport_failure_becomes_could_not_look_with_both_causes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State (c). Both channels down -> every concrete cause in one reason."""
    _gh_absent(monkeypatch)
    monkeypatch.setattr(generate_status, "run", _fake_run())
    _patch_rest(monkeypatch, 0, "URLError: name resolution failed")

    status, reason = generate_status.ci_signal()

    assert status == "UNVERIFIABLE"
    assert "not installed" in reason
    assert "unreachable" in reason
    assert "name resolution failed" in reason


@pytest.mark.parametrize(
    ("http_status", "body", "expected_fragment"),
    [
        (401, '{"message":"Bad credentials"}', "HTTP 401"),
        (403, '{"message":"API rate limit exceeded"}', "rate limited"),
        (404, '{"message":"Not Found"}', "HTTP 404"),
        (500, "boom", "HTTP 500"),
    ],
)
def test_http_refusals_name_themselves(
    monkeypatch: pytest.MonkeyPatch,
    http_status: int,
    body: str,
    expected_fragment: str,
) -> None:
    _gh_absent(monkeypatch)
    monkeypatch.setattr(generate_status, "run", _fake_run())
    _patch_rest(monkeypatch, http_status, body)

    status, reason = generate_status.ci_signal()

    assert status == "UNVERIFIABLE"
    assert expected_fragment in reason


def test_unparseable_remote_url_is_its_own_honest_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A remote that does not point at GitHub is not a silent skip."""
    _gh_absent(monkeypatch)
    monkeypatch.setattr(
        generate_status, "run", _fake_run(remote_url="https://gitlab.example.com/team/project.git")
    )
    _patch_rest(monkeypatch, 200, _rest_body("success"))  # must never be reached

    status, reason = generate_status.ci_signal()

    assert status == "UNVERIFIABLE"
    assert "gitlab.example.com" in reason
    assert "not github.com" in reason


def test_garbage_remote_url_is_reported_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    _gh_absent(monkeypatch)
    monkeypatch.setattr(generate_status, "run", _fake_run(remote_url="this-is-not-a-remote"))
    _patch_rest(monkeypatch, 200, _rest_body("success"))

    status, reason = generate_status.ci_signal()

    assert status == "UNVERIFIABLE"
    assert "could not parse" in reason


def test_missing_origin_remote_names_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remotes exist, but origin specifically does not -- its own stated state.

    The early 'no remote at all' branch must not swallow this distinct case.
    """
    _gh_absent(monkeypatch)
    monkeypatch.setattr(
        generate_status,
        "run",
        _fake_run(remote_url=None, remote_listing="upstream\thttps://github.com/x/y.git (fetch)"),
    )
    _patch_rest(monkeypatch, 200, _rest_body("success"))

    status, reason = generate_status.ci_signal()

    assert status == "UNVERIFIABLE"
    assert "'origin'" in reason


def test_malformed_api_json_is_could_not_look_not_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _gh_absent(monkeypatch)
    monkeypatch.setattr(generate_status, "run", _fake_run())
    _patch_rest(monkeypatch, 200, "<html>not json</html>")

    status, reason = generate_status.ci_signal()

    assert status == "UNVERIFIABLE"
    assert "parse" in reason


# ---------------------------------------------------------------------------
# gh stays primary when it works.
# ---------------------------------------------------------------------------


def test_gh_present_still_primary_and_rest_never_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path must not grow a mandatory API round-trip."""
    _gh_present(monkeypatch)
    gh_payload = json.dumps([{"headSha": HEAD, "conclusion": "success"}])
    monkeypatch.setattr(generate_status, "run", _fake_run(gh_output=(0, gh_payload)))

    def forbidden_http_get(*args: Any, **kwargs: Any) -> tuple[int, str]:
        raise AssertionError("REST fallback called although gh answered")

    monkeypatch.setattr(generate_status, "_http_get", forbidden_http_get)

    status, reason = generate_status.ci_signal()

    assert status == "PASS"
    assert HEAD[:8] in reason


def test_gh_error_falls_through_to_a_working_rest_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _gh_present(monkeypatch)
    monkeypatch.setattr(generate_status, "run", _fake_run(gh_output=(1, "gh: auth failed")))
    _patch_rest(monkeypatch, 200, _rest_body("success"))

    status, _reason = generate_status.ci_signal()

    assert status == "PASS"


# ---------------------------------------------------------------------------
# The transport seam itself: stdlib urllib mapped to (status, body).
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


def test_http_get_returns_body_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(b'{"ok": true}', status=200),
    )

    code, body = generate_status._http_get("https://api.github.com/x", {})

    assert code == 200
    assert '"ok"' in body


def test_http_get_maps_http_errors_to_their_code_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_http_error(request: Any, timeout: Any = None) -> None:
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            email.message.Message(),
            io.BytesIO(b'{"message":"rate limit"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", raise_http_error)

    code, body = generate_status._http_get("https://api.github.com/x", {})

    assert code == 403
    assert "rate limit" in body


def test_http_get_maps_transport_failures_to_status_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_url_error(request: Any, timeout: Any = None) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", raise_url_error)

    code, detail = generate_status._http_get("https://api.github.com/x", {})

    assert code == 0
    assert "connection refused" in detail
