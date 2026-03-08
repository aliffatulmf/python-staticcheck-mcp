from __future__ import annotations

import asyncio
import codecs
import contextlib
import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import anyio
from fastmcp import FastMCP

from .types import UNKNOWN_ERROR, AnalysisResult, Value, ExplainResult, Issue

MCP_NAME = "python-staticcheck-mcp"

INSTRUCTIONS = """
This MCP server provides automated static analysis for Go code using staticcheck.

## Capabilities
- Run staticcheck on Go files or directories to find errors and warnings.
- Get detailed explanations for specific staticcheck check codes.
- Scan entire Go packages/directories with relative paths using Go package patterns.

## Available Tools

1. `python_staticcheck_checks(path, checks=None)`:
   - Analyze a **single Go file** for static analysis issues.
   - `path`: Must be an **absolute path** (e.g., "C:/repo/pkg/main.go").
   - `checks`: Optional filter for specific check codes (e.g., "SA4006" or ["SA4006", "SA5000"]).
   - Returns a list of issues with severity, code, file, line, column, and message.

2. `python_staticcheck_package(path, checks=None)`:
   - Analyze **all Go files directly in a package/directory** (non-recursive).
   - `path`: Can be **relative or absolute** (e.g., "sandbox", "./cmd", "C:/repo/pkg").
   - **Only checks .go files in the specified directory, NOT in subdirectories**.
   - `checks`: Optional filter for specific check codes (same as above).
   - Returns a list of issues with severity, code, file, line, column, and message.

3. `python_staticcheck_explain(code)`:
   - Get a detailed explanation for a specific staticcheck check code.
   - `code`: A string like "SA4006", "SA5000", etc.
   - Returns human-readable explanation of the issue and how to fix it.

## Prerequisites
- `staticcheck` binary must be installed and available in the system PATH.
- For Go projects, ensure the project is properly initialized with go.mod.

## Common Check Codes
- SA4006: Unused value in assignment
- SA5000: Empty critical section
- SA6005: Unnecessary allocation
- ST1000: Missing package comment

## Usage Workflow for Agents

1. **For single file analysis:**
   - Use `python_staticcheck_checks` with an absolute file path.

2. **For package/directory analysis:**
   - Use `python_staticcheck_package` with a relative or absolute path.
   - **Non-recursive**: Only checks .go files directly in the directory (subdirectories ignored).
   - Example: For directory `a` with files `a/b.go`, `a/c.go`, `a/d/e.go`, only `a/b.go` and `a/c.go` are checked.

3. **For understanding issues:**
   - For each issue found, use `python_staticcheck_explain` to understand the problem deeply.
   - Use the explanation to suggest appropriate code fixes.

4. **If staticcheck is not found:**
   - Inform the user that it must be installed.
"""

mcp = FastMCP(
    name=MCP_NAME,
    instructions=INSTRUCTIONS,
)

_staticcheck_bin = shutil.which("staticcheck")


def _is_staticcheck_available() -> bool:
    return _staticcheck_bin is not None


def _flatten(*args: object) -> list[str]:
    flat: list[str] = []

    def _recurse(item: object) -> None:
        if item is None:
            return
        if isinstance(item, (str, bytes, bytearray, Path)):
            flat.append(str(item))
            return
        if isinstance(item, Iterable):
            for sub in item:
                _recurse(sub)
            return
        flat.append(str(item))

    for a in args:
        _recurse(a)

    return flat


async def read_stream(stream: asyncio.StreamReader, chunk_size: int, chunks: list[bytes]):
    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)


async def _wait_for_process_exit(proc: asyncio.subprocess.Process) -> None:
    try:
        await asyncio.wait_for(proc.wait(), timeout=1.0)
    except (TimeoutError, AttributeError):
        return


async def _cleanup_process(proc: asyncio.subprocess.Process, tasks: list[asyncio.Task[object]]):
    if hasattr(proc, "kill"):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()

    for task in tasks:
        task.cancel()

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    await _wait_for_process_exit(proc)


async def _run_staticcheck(
    *args: str,
    style: Literal["text", "json", "none"] = "text",
    chunk_size: int = 8192,
) -> Value:
    if not _is_staticcheck_available():
        return Value(done=False, value="staticcheck binary not found in PATH.")

    flat_args = _flatten(*args)

    cmd_args = [_staticcheck_bin]
    if style == "none":
        cmd_args.extend(flat_args)
    else:
        cmd_args.extend(["-f", style])
        cmd_args.extend(flat_args)

    proc = await asyncio.create_subprocess_exec(
        *cmd_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    tasks = []
    try:
        stdout_stream = getattr(proc, "stdout", None)
        stderr_stream = getattr(proc, "stderr", None)

        if stdout_stream is not None or stderr_stream is not None:
            stdout_chunks = []
            stderr_chunks = []

            tasks = [asyncio.create_task(proc.wait())]

            stdout_task = None
            stderr_task = None

            if stdout_stream is not None:
                stdout_task = asyncio.create_task(read_stream(stdout_stream, chunk_size, stdout_chunks))
                tasks.append(stdout_task)

            if stderr_stream is not None:
                stderr_task = asyncio.create_task(read_stream(stderr_stream, chunk_size, stderr_chunks))
                tasks.append(stderr_task)

            await asyncio.wait_for(asyncio.gather(*tasks), timeout=30.0)

            stdout_bytes = b"".join(stdout_chunks)
            stderr_bytes = b"".join(stderr_chunks)
        else:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except TimeoutError:
        await _cleanup_process(proc, tasks)
        return Value(done=False, value="staticcheck execution timed out.")
    except Exception as e:
        await _cleanup_process(proc, tasks)
        return Value(done=False, value=f"Error reading streams: {e}")

    out = codecs.decode(stdout_bytes, "utf-8", errors="replace").strip()
    err = codecs.decode(stderr_bytes, "utf-8", errors="replace").strip()

    if style == "json" and not out and not err:
        return Value(done=True, value="")
    if out:
        return Value(done=True, value=out)
    if err:
        return Value(done=False, value=err)
    return Value(done=False, value=UNKNOWN_ERROR)


def _parse_staticcheck_json(raw: str, fallback_path: str) -> list[Issue]:
    issues: list[Issue] = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue

        location = r["location"]
        file_path = location["file"] or fallback_path

        line_num = int(location["line"])
        col_num = int(location["column"])

        severity = r["severity"]
        code = r["code"]
        message_raw = r["message"]

        try:
            message = message_raw.encode("utf-8").decode("unicode_escape")
        except (UnicodeEncodeError, UnicodeDecodeError, UnicodeError):
            message = message_raw

        issues.append(
            Issue(
                severity=severity,
                code=code,
                file=file_path,
                line=line_num,
                column=col_num,
                message=message,
            )
        )

    return issues


def _build_checks_cmd(path: str, checks: str | list[str] | None) -> list[str]:
    args: list[str] = []
    if checks:
        if isinstance(checks, list):
            checks = ",".join(checks)
        args.extend(["-checks", str(checks)])

    if "..." in path:
        args.append(str(path))
    else:
        args.append(str(Path(path).resolve()))

    return args


@mcp.tool
async def psc_explain(code: str):
    """
    Return the official staticcheck explanation for a specific check code.

    This tool invokes `staticcheck -explain <CODE>` to retrieve detailed documentation
    about a staticcheck error/warning code. It is useful for agents and developers
    who need to understand what a specific staticcheck issue means and how to fix it.

    Parameters
    ----------
    code : str
        The staticcheck check code to explain. Must be a string like "SA4006", "SA5000", etc.
        Example codes:
          - SA4006: "unused value in assignment"
          - SA5000: "empty critical section"
          - SA6005: "unnecessary allocation"
          - ST1000: "missing package comment"

    Returns
    -------
    str | dict
        On success: Returns the plain text explanation from staticcheck.
        ```text
        <explanation text>
        ```

        On failure (staticcheck execution error):
        ```json
        {"ok": false, "message": "<error>", "code": "<CODE>"}
        ```

        On failure (invalid input):
        ```json
        {"ok": false, "message": "`code` must be a string.", "code": null}
        ```

    Examples
    --------
    >>> await python_staticcheck_explain("SA4006")
    'The value assigned to ... (plain text explanation)'

    >>> await python_staticcheck_explain(123)
    {'ok': False, 'message': '`code` must be a string.', 'code': None}

    Usage for Agents
    ----------------
    1. When encountering a staticcheck error code in a Go file, call this tool with the code.
    2. Use the returned explanation to understand the issue and suggest fixes.
    3. Common check codes start with two letters (SA, ST, etc.) followed by 4 digits.

    Notes
    -----
    - Execution timeout: 30 seconds.
    - Requires `staticcheck` binary to be installed and available in PATH.
    """
    if not isinstance(code, str):
        return ExplainResult(ok=False, message="`code` must be a string.", code=None).model_dump()
    result = await _run_staticcheck("-explain", code, style="none")
    result_value = codecs.decode(str(result.value), "unicode_escape", errors="replace").strip()
    if not result.done:
        return ExplainResult(ok=False, message=result_value, code=code).model_dump()
    return result_value


@mcp.tool
async def psc_analysis(
    path: str,
    checks: str | list[str] | None = None,
):
    """
    Run staticcheck on a specified Go file or directory and return structured findings.

    This tool executes `staticcheck` with optional check filters and returns a list of
    issues (errors/warnings) in a structured JSON format. It is designed for agents
    to analyze Go code quality and identify specific static analysis problems.

    Parameters
    ----------
    path : str
        Absolute path to a Go file or directory to analyze.
        Must be an absolute path (e.g., "C:/repo/pkg/main.go" or "/home/user/project").
        Relative paths will result in an error.
        The path must exist and be a valid file or directory.
    checks : str | list[str] | None, optional
        Filter which staticcheck rules to run.
        - If `None`: runs all default checks.
        - If `str`: comma-separated list or single check code (e.g., "SA4006" or "SA4006,SA5000").
        - If `list[str]`: list of check codes (e.g., ["SA4006", "SA5000"]).
        Common check codes:
          - SA4006: unused value in assignment
          - SA5000: empty critical section
          - SA6005: unnecessary allocation
          - ST1000: missing package comment

    Returns
    -------
    dict
        On success (found issues or no issues):
        ```json
        {"ok": true, "issues": [
          {"severity": "error", "code": "SA4006", "file": "/path/to/file.go", "line": 10, "column": 5, "message": "unused value"},
          {"severity": "warning", "code": "SA5000", "file": "/path/to/file.go", "line": 20, "column": 2, "message": "empty critical section"}
        ]}
        ```

        On failure (invalid path):
        ```json
        {"ok": false, "message": "`path` must be an absolute string path.", "code": null, "path": "<path>"}
        ```
        or
        ```json
        {"ok": false, "message": "File not found: <path>", "code": null, "path": "<path>"}
        ```

        On failure (staticcheck execution error):
        ```json
        {"ok": false, "error": "<staticcheck error message>"}
        ```

    Examples
    --------
    >>> await python_staticcheck_checks("C:/repo/pkg/main.go")
    {'ok': True, 'issues': [{'severity': 'error', 'code': 'SA4006', 'file': 'C:/repo/pkg/main.go', 'line': 10, 'column': 5, 'message': 'unused value'}]}

    >>> await python_staticcheck_checks("C:/repo/pkg", checks=["SA4006", "SA5000"])
    {'ok': True, 'issues': [...]}

    >>> await python_staticcheck_checks("relative/path.go")
    {'ok': False, 'message': '`path` must be an absolute string path.', 'code': None, 'path': 'relative/path.go'}

    Usage for Agents
    ----------------
    1. When analyzing a Go codebase, call this tool with the file or directory path.
    2. Optionally filter specific check codes if you only care about certain issues.
    3. Parse the `issues` list to understand:
       - `severity`: "error" or "warning"
       - `code`: the staticcheck rule ID
       - `file`, `line`, `column`: location of the issue
       - `message`: description of the problem
    4. Use the issue details to suggest code fixes or improvements.
    5. For detailed explanation of a specific check code, use `python_staticcheck_explain`.

    Notes
    -----
    - Execution timeout: 30 seconds per file/directory.
    - Requires `staticcheck` binary to be installed and available in PATH.
    - Path validation: path must be absolute and exist (file or directory).
    """
    if not isinstance(path, str) or not Path(path).is_absolute():
        return AnalysisResult(
            ok=False,
            message="`path` must be an absolute string path.",
            code=None,
            path=path,
        ).model_dump()

    if not await anyio.Path(path).is_file():
        return AnalysisResult(
            ok=False,
            message=f"File not found: {path}",
            code=None,
            path=path,
        ).model_dump()

    args = _build_checks_cmd(path, checks)
    result = await _run_staticcheck(*args, style="json")

    if not result.done:
        res_val = result.value
        if isinstance(result.value, str):
            res_val = result.value.replace(r"\\\\", "/")
        return AnalysisResult(
            ok=False,
            error=res_val or UNKNOWN_ERROR,
        ).model_dump()

    issues = _parse_staticcheck_json(result.value, fallback_path=path)
    return AnalysisResult(ok=True, issues=issues).model_dump()


@mcp.tool
async def psc_package_analysis(
    path: str,
    checks: str | list[str] | None = None,
):
    """
    Run staticcheck on all Go files in a package or directory (non-recursive).

    This tool analyzes only the .go files directly in the specified directory,
    NOT in subdirectories. For example, if directory 'a' contains:
      a/b.go, a/c.go, a/d/e.go, a/d/f.go
    Only a/b.go and a/c.go will be checked. a/d/e.go and a/d/f.go are ignored.

    Parameters
    ----------
    path : str
        Relative or absolute path to a Go package directory to analyze.
        - Can be a relative path (e.g., "sandbox", "./cmd") or an absolute path.
        - Only .go files directly in this directory will be checked (non-recursive).
    checks : str | list[str] | None, optional
        Filter which staticcheck rules to run.
        - If `None`: runs all default checks.
        - If `str`: comma-separated list or single check code.
        - If `list[str]`: list of check codes.

    Returns
    -------
    dict
        Same structure as python_staticcheck_checks with "ok" and "issues".

    Examples
    --------
    >>> await python_staticcheck_package("sandbox")
    {'ok': True, 'issues': [...]}
    >>> await python_staticcheck_package("./cmd", checks=["SA4006"])
    {'ok': True, 'issues': [...]}

    Notes
    -----
    - Execution timeout: 30 seconds.
    - Requires `staticcheck` binary to be installed and available in PATH.
    - **Non-recursive**: Only checks .go files directly in the specified directory.
    - Subdirectories are ignored (e.g., "a/d/e.go" will NOT be checked for path "a").
    """
    if not isinstance(path, str) or not path.strip():
        return AnalysisResult(ok=False, message="`path` must be a non-empty string.", code=None, path=path).model_dump()

    clean_path = (
        str(await anyio.Path(path).resolve())
        .replace("/...", "")
        .replace("\\...", "")
        .replace("...", "")
        .rstrip("/\\")
        .rstrip()
    )

    anyio_path = anyio.Path(clean_path)
    if not anyio_path.is_absolute():
        return AnalysisResult(
            ok=False,
            message="`path` must be an absolute string path after resolution.",
            code=None,
            path=path,
        ).model_dump()

    if not await anyio_path.exists():
        return AnalysisResult(ok=False, message=f"Path not found: {path}", code=None, path=path).model_dump()

    if not await anyio_path.is_dir():
        return AnalysisResult(ok=False, message=f"Path must be a directory: {path}", code=None, path=path).model_dump()

    go_files = []
    async for entry in anyio_path.iterdir():
        if await entry.is_file() and entry.name.endswith(".go"):
            go_files.append(entry)

    if not go_files:
        return AnalysisResult(ok=True, issues=[]).model_dump()

    all_issues: list[Issue] = []
    for go_file in go_files:
        file_path = str(go_file)
        args = _build_checks_cmd(file_path, checks)
        result = await _run_staticcheck(*args, style="json")
        if result.done:
            issues = _parse_staticcheck_json(result.value, fallback_path=file_path)
            all_issues.extend(issues)

    return AnalysisResult(ok=True, issues=all_issues).model_dump()


def main():
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
