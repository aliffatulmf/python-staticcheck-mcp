from __future__ import annotations

import asyncio
import json
import runpy
import sys
from pathlib import Path

import pytest

import python_staticcheck_mcp.server as server
from python_staticcheck_mcp.types import UNKNOWN_ERROR

SAMPLES_STATICCHECK_DIR = Path(__file__).resolve().parents[1] / "samples" / "staticcheck"


def test_main_runs_mcp_stdio_without_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_run(*, transport, show_banner):
        called["transport"] = transport
        called["show_banner"] = show_banner

    monkeypatch.setattr(server.mcp, "run", fake_run)

    server.main()

    assert called == {"transport": "stdio", "show_banner": False}


def test_module_entrypoint_invokes_main(monkeypatch: pytest.MonkeyPatch) -> None:
    import fastmcp

    calls: list[tuple[str, str, bool]] = []

    def fake_run(self, *, transport, show_banner):
        calls.append((self.name, transport, show_banner))

    monkeypatch.setattr(fastmcp.FastMCP, "run", fake_run, raising=True)

    existing_module = sys.modules.pop("python_staticcheck_mcp.server", None)
    try:
        runpy.run_module("python_staticcheck_mcp.server", run_name="__main__")
    finally:
        if existing_module is not None:
            sys.modules["python_staticcheck_mcp.server"] = existing_module

    assert calls[-1] == (server.MCP_NAME, "stdio", False)


@pytest.mark.asyncio
async def test_python_staticcheck_package_accepts_relative_path(monkeypatch):
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess(
            stdout=b'{"severity":"warning","code":"ST1000","location":{"file":"samples/staticcheck/s1.go","line":1,"column":1},"message":"missing package comment"}\n',
            returncode=1,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    result = await server.python_staticcheck_package("samples/staticcheck")
    assert result["ok"] is True
    assert "issues" in result


@pytest.mark.asyncio
async def test_python_staticcheck_package_with_ellipsis_pattern(monkeypatch):
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")
    seen_args: list[tuple] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen_args.append(args)
        return FakeProcess(stdout=b"", returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    result = await server.python_staticcheck_package("samples/staticcheck/...")
    assert result["ok"] is True
    assert not any("..." in str(arg) for arg in seen_args[0]), "Expected no ... pattern in args"


@pytest.mark.asyncio
async def test_python_staticcheck_package_with_checks_filter(monkeypatch):
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")
    seen_args: list[tuple] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen_args.append(args)
        return FakeProcess(stdout=b"", returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    result = await server.python_staticcheck_package("samples/staticcheck", checks=["SA4006", "ST1000"])
    assert result["ok"] is True
    assert any("-checks" in str(arg) for arg in seen_args[0])


@pytest.mark.asyncio
async def test_python_staticcheck_package_rejects_empty_string(monkeypatch):
    result = await server.python_staticcheck_package("")
    assert result["ok"] is False
    assert "`path` must be a non-empty string." in result["message"]


@pytest.mark.asyncio
async def test_python_staticcheck_package_handles_nonexistent_path(monkeypatch):
    result = await server.python_staticcheck_package("./nonexistent/path")
    assert result["ok"] is False
    assert "Path not found" in result["message"]


@pytest.mark.asyncio
async def test_python_staticcheck_package_accepts_absolute_path(monkeypatch):
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")
    seen_args: list[tuple] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen_args.append(args)
        return FakeProcess(stdout=b"", returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    abs_path = str(SAMPLES_STATICCHECK_DIR)
    result = await server.python_staticcheck_package(abs_path)
    assert result["ok"] is True
    assert any(abs_path in str(arg) for arg in seen_args[0])


def test_flatten_handles_none_and_iterables():
    # None should be skipped, iterables should be flattened
    assert server._flatten(None, [1, 2], (3,)) == ["1", "2", "3"]


def test_build_checks_cmd_variants():
    # None checks
    path = str(SAMPLES_STATICCHECK_DIR / "s1.go")
    assert server._build_checks_cmd(path, None) == [path]
    # String checks
    assert server._build_checks_cmd(path, "SA4006") == ["-checks", "SA4006", path]
    # List checks
    assert server._build_checks_cmd(path, ["SA4006", "SA5000"]) == ["-checks", "SA4006,SA5000", path]
    # Path with ...
    assert server._build_checks_cmd("foo/...", None) == ["foo/..."]


def test_parse_staticcheck_json_handles_jsondecodeerror():
    # Should skip invalid JSON lines
    raw = "{invalid json}\n" + json.dumps(
        {"severity": "error", "code": "SA4006", "location": {"file": "", "line": "1", "column": "1"}, "message": "msg"}
    )
    issues = server._parse_staticcheck_json(raw, fallback_path="fallback.go")
    assert len(issues) == 1
    assert issues[0].file == "fallback.go"


@pytest.mark.asyncio
async def test_run_staticcheck_timeout(monkeypatch):
    import warnings

    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    class TimeoutProc:
        async def communicate(self):
            await asyncio.sleep(0.1)
            return b"", b""

        def kill(self):
            pass

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        return TimeoutProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def fake_wait_for(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = await server._run_staticcheck("foo.go")

    assert not result.done
    assert "timed out" in result.value


@pytest.mark.asyncio
async def test_run_staticcheck_fallback(monkeypatch):
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    class DummyProc:
        async def communicate(self):
            return b"", b""

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        return DummyProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    result = await server._run_staticcheck("foo.go")
    assert not result.done
    assert result.value == UNKNOWN_ERROR


class FakeProcess:
    def __init__(self, *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 1):
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    async def wait(self) -> int:
        return self._returncode


@pytest.mark.asyncio
async def test_run_staticcheck_style_none_and_stderr_return_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")
    seen: list[tuple[object, ...]] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen.append(args)
        return FakeProcess(stderr=b"boom\n", returncode=2)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await server._run_staticcheck("-explain", "SA4006", style="none")

    assert result.done is False
    assert result.value == "boom"
    assert seen == [("staticcheck", "-explain", "SA4006")]


@pytest.mark.asyncio
async def test_run_staticcheck_returns_unknown_error_for_empty_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    async def returns_zero(*args, **kwargs):
        return FakeProcess(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", returns_zero)
    result_zero = await server._run_staticcheck("./...")

    assert result_zero.done is False
    assert result_zero.value == UNKNOWN_ERROR

    async def returns_empty_failure(*args, **kwargs):
        return FakeProcess(returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", returns_empty_failure)
    result_empty = await server._run_staticcheck("./...")

    assert result_empty.done is False
    assert result_empty.value == UNKNOWN_ERROR


def test_parse_staticcheck_json_skips_blank_lines_and_applies_fallback() -> None:
    raw = "\n".join(
        [
            json.dumps(
                {
                    "severity": "error",
                    "code": "SA4006",
                    "location": {"file": "", "line": "12", "column": "7"},
                    "message": r"unused value: \u2192 branch",
                }
            ),
            "",
            json.dumps(
                {
                    "severity": "warning",
                    "code": "SA5000",
                    "location": {"file": "C:/repo/pkg/file.go", "line": 2, "column": 3},
                    "message": "already decoded",
                }
            ),
        ]
    )

    issues = server._parse_staticcheck_json(raw, fallback_path="C:/repo/fallback.go")

    assert issues == [
        server.Issue(
            severity="error",
            code="SA4006",
            file="C:/repo/fallback.go",
            line=12,
            column=7,
            message="unused value: → branch",
        ),
        server.Issue(
            severity="warning",
            code="SA5000",
            file="C:/repo/pkg/file.go",
            line=2,
            column=3,
            message="already decoded",
        ),
    ]


def test_build_checks_cmd_supports_none_string_and_list(tmp_path) -> None:
    target = tmp_path / "pkg" / "main.go"
    target.parent.mkdir()
    target.write_text("package main\n", encoding="utf-8")

    assert server._build_checks_cmd(str(target), None) == [str(target.resolve())]
    assert server._build_checks_cmd(str(target), "SA4006") == ["-checks", "SA4006", str(target.resolve())]
    assert server._build_checks_cmd(str(target), ["SA4006", "SA5000"]) == [
        "-checks",
        "SA4006,SA5000",
        str(target.resolve()),
    ]


@pytest.mark.asyncio
async def test_python_staticcheck_explain_validates_input_type() -> None:
    response = await server.python_staticcheck_explain(123)

    assert response == {
        "ok": False,
        "message": "`code` must be a string.",
        "code": None,
    }


@pytest.mark.asyncio
async def test_python_staticcheck_explain_handles_runner_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(*args, **kwargs):
        assert args == ("-explain", "SA4006")
        assert kwargs == {"style": "none"}
        return server.ExecResult(done=False, value="staticcheck is unhappy")

    monkeypatch.setattr(server, "_run_staticcheck", fake_run)

    response = await server.python_staticcheck_explain("SA4006")

    assert response["ok"] is False
    assert response["code"] == "SA4006"
    assert isinstance(response["message"], str)
    assert response["message"]


@pytest.mark.asyncio
async def test_python_staticcheck_explain_returns_explanation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(*args, **kwargs):
        return server.ExecResult(done=True, value=" explanation text \n")

    monkeypatch.setattr(server, "_run_staticcheck", fake_run)

    response = await server.python_staticcheck_explain("SA4006")

    assert response == "explanation text"


@pytest.mark.asyncio
async def test_python_staticcheck_checks_rejects_non_absolute_paths() -> None:
    response = await server.python_staticcheck_checks("sandbox/sa6.go")

    assert response == {
        "ok": False,
        "message": "`path` must be an absolute string path.",
        "code": None,
        "path": "sandbox/sa6.go",
    }


@pytest.mark.asyncio
async def test_python_staticcheck_checks_normalizes_runner_errors(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "windows.go"
    target.write_text("package main\n", encoding="utf-8")

    async def fake_run(*args, **kwargs):
        assert args == ("-checks", "SA4006,SA5000", str(target.resolve()))
        assert kwargs == {"style": "json"}
        return server.ExecResult(done=False, value=r"C:\\\\repo\\\\windows.go: bad thing")

    monkeypatch.setattr(server, "_run_staticcheck", fake_run)
    response = await server.python_staticcheck_checks(str(target), checks=["SA4006", "SA5000"])
    assert response == {"ok": False, "error": r"C:/repo/windows.go: bad thing"}


@pytest.mark.asyncio
async def test_python_staticcheck_checks_returns_structured_issues(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "main.go"
    target.write_text("package main\n", encoding="utf-8")
    raw = json.dumps(
        {
            "severity": "warning",
            "code": "SA4006",
            "location": {"file": None, "line": 9, "column": 11},
            "message": r"unused assignment in \u03bb path",
        }
    )

    async def fake_run(*args, **kwargs):
        assert args == (str(target.resolve()),)
        assert kwargs == {"style": "json"}
        return server.ExecResult(done=True, value=raw)

    monkeypatch.setattr(server, "_run_staticcheck", fake_run)

    response = await server.python_staticcheck_checks(str(target))

    assert response == {
        "ok": True,
        "issues": [
            {
                "severity": "warning",
                "code": "SA4006",
                "file": str(target),
                "line": 9,
                "column": 11,
                "message": "unused assignment in λ path",
            }
        ],
    }


class ChunkedStream:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)

    async def read(self, chunk_size: int) -> bytes:
        await asyncio.sleep(0)
        if not self._chunks:
            return b""

        chunk = self._chunks.pop(0)
        if len(chunk) <= chunk_size:
            return chunk

        self._chunks.insert(0, chunk[chunk_size:])
        return chunk[:chunk_size]


class HangingStream:
    async def read(self, chunk_size: int) -> bytes:
        await asyncio.Future()


class StreamingFakeProcess:
    """Fake process that supports deterministic streaming reads for testing."""

    def __init__(
        self,
        *,
        stdout_chunks: list[bytes] | None = None,
        stderr_chunks: list[bytes] | None = None,
        returncode: int = 1,
    ):
        self._returncode = returncode
        self.killed = False
        self.stdout = ChunkedStream(stdout_chunks or [])
        self.stderr = ChunkedStream(stderr_chunks or [])

    async def wait(self) -> int:
        await asyncio.sleep(0)
        return self._returncode

    def kill(self) -> None:
        self.killed = True


class HangingStreamingProcess:
    def __init__(self):
        self.stdout = HangingStream()
        self.stderr = HangingStream()
        self.killed = False

    async def wait(self) -> int:
        await asyncio.Future()

    def kill(self) -> None:
        self.killed = True


class NoStreamingFakeProcess:
    """Fake process without streaming support (fallback test)"""

    def __init__(self, *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 1):
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    async def wait(self) -> int:
        return self._returncode


@pytest.mark.asyncio
async def test_run_staticcheck_streaming_reads_stdout_and_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that streaming read works correctly for normal processes."""
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    test_stdout = [b"line1\n", b"line2\nline3\n"]
    test_stderr = [b"warning1\n", b"warning2\n"]

    async def fake_create_subprocess_exec(*args, **kwargs):
        return StreamingFakeProcess(stdout_chunks=test_stdout, stderr_chunks=test_stderr, returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await server._run_staticcheck("test.go", style="text")

    assert result.done is True
    assert result.value == "line1\nline2\nline3"


@pytest.mark.asyncio
async def test_run_staticcheck_streaming_concurrent_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that streaming handles multi-chunk output larger than chunk_size."""
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    large_stdout = [b"x" * 5000, b"x" * 5000, b"x" * 10000]
    large_stderr = [b"y" * 4000, b"y" * 11000]

    async def fake_create_subprocess_exec(*args, **kwargs):
        return StreamingFakeProcess(stdout_chunks=large_stdout, stderr_chunks=large_stderr, returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await server._run_staticcheck("test.go", style="none")

    assert result.done is True
    assert len(result.value) == 20000


@pytest.mark.asyncio
async def test_run_staticcheck_fallback_to_communicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test fallback to communicate() for processes without streaming support"""
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    test_stdout = b"fallback stdout\n"
    test_stderr = b"fallback stderr\n"

    async def fake_create_subprocess_exec(*args, **kwargs):
        return NoStreamingFakeProcess(stdout=test_stdout, stderr=test_stderr)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await server._run_staticcheck("test.go", style="text")

    assert result.done is True
    assert result.value == "fallback stdout"


@pytest.mark.asyncio
async def test_run_staticcheck_streaming_single_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test streaming with data that fits in a single chunk."""
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    test_stdout = [b"single chunk output\n"]

    async def fake_create_subprocess_exec(*args, **kwargs):
        return StreamingFakeProcess(stdout_chunks=test_stdout, returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await server._run_staticcheck("test.go", style="text")

    assert result.done is True
    assert result.value == "single chunk output"


@pytest.mark.asyncio
async def test_run_staticcheck_streaming_empty_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test streaming with empty output."""
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return StreamingFakeProcess(stdout_chunks=[], stderr_chunks=[], returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await server._run_staticcheck("test.go", style="json")

    assert result.done is True
    assert result.value == ""


@pytest.mark.asyncio
async def test_run_staticcheck_streaming_large_json_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test streaming with large JSON output across multiple chunks."""
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")

    json_lines = []
    for i in range(100):
        payload = {
            "severity": "warning",
            "code": "ST1000",
            "location": {"file": f"file{i}.go", "line": i, "column": 1},
            "message": "missing package comment",
        }
        json_line = json.dumps(payload) + "\n"
        json_lines.append(json_line)

    test_output = "".join(json_lines).encode("utf-8")
    output_chunks = [test_output[:4096], test_output[4096:8192], test_output[8192:]]

    async def fake_create_subprocess_exec(*args, **kwargs):
        return StreamingFakeProcess(stdout_chunks=output_chunks, returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await server._run_staticcheck("test.go", style="json")

    assert result.done is True
    assert len(result.value) > 0
    output_str = result.value if isinstance(result.value, str) else result.value.decode("utf-8")
    assert '"severity"' in output_str


@pytest.mark.asyncio
async def test_run_staticcheck_streaming_timeout_kills_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_staticcheck_bin", "staticcheck")
    proc = HangingStreamingProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return proc

    real_wait_for = asyncio.wait_for

    async def fake_wait_for(awaitable, *args, **kwargs):
        if hasattr(awaitable, "__class__") and awaitable.__class__.__name__ == "_GatheringFuture":
            raise TimeoutError()
        return await real_wait_for(awaitable, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    result = await server._run_staticcheck("test.go", style="json")

    assert result.done is False
    assert result.value == "staticcheck execution timed out."
    assert proc.killed is True
