from __future__ import annotations

import asyncio
import codecs
import json
import shutil
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from .types import UNKNOWN_ERROR, ExecResult, Issue

MCP_NAME = "python-staticcheck-mcp"


mcp = FastMCP(name=MCP_NAME)

_staticcheck_bin = shutil.which("staticcheck")


def _is_staticcheck_available() -> bool:
    return _staticcheck_bin is not None


def _flatten(*args: str) -> list:
    flat_args = []
    for arg in args:
        if isinstance(arg, (list, tuple)):
            flat_args.extend(arg)
        else:
            flat_args.append(arg)

    return flat_args


async def _run_staticcheck(*args: str, style: Literal["text", "json", "none"] = "text") -> ExecResult:
    if not _is_staticcheck_available():
        return ExecResult(done=False, value="staticcheck binary not found in PATH.")

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

    stdout, stderr = await proc.communicate()
    returncode = await proc.wait()

    # returncode != 0 mean execution failed, but we want to capture stderr in that case to provide feedback
    if returncode != 0 or stderr:
        return ExecResult(done=False, value=codecs.decode(stderr, "utf-8", errors="replace").strip())
    if returncode == 0 or stdout:
        return ExecResult(done=True, value=codecs.decode(stdout, "utf-8", errors="replace").strip())


def _parse_staticcheck_json(raw: str, fallback_path: str) -> list[Issue]:
    def parse(line: str) -> Issue | None:
        line = line.strip()
        if not line:
            return None

        r = json.loads(line)

        if r["location"]["file"] is None or r["location"]["file"] == "":
            r["location"]["file"] = fallback_path

        return Issue(
            severity=r["severity"],
            code=r["code"],
            file=r["location"]["file"],
            line=int(r["location"]["line"]),
            column=int(r["location"]["column"]),
            message=codecs.decode(r["message"], "unicode_escape"),
        )

    issues = []
    for line in raw.splitlines():
        item = parse(line)
        if item:
            issues.append(item)
    return issues


def _build_checks_cmd(path: str, checks: str | list[str] | None) -> list[str]:
    args: list[str] = []
    if checks:
        if not isinstance(checks, str):
            checks = ",".join(map(str, checks))
        args.extend(["-checks", checks])

    args.append(str(Path(path).resolve()))
    return args


@mcp.tool
async def python_staticcheck_explain(code: str):
    """
    Return the official staticcheck explanation for a specific check code.
    Accepts a staticcheck identifier (e.g., "SA4006") and invokes staticcheck -explain <check>.
    """
    if not isinstance(code, str):
        return {"ok": False, "message": "`code` must be a string.", "code": None}

    result = await _run_staticcheck("-explain", code, style="none")
    result_value = codecs.decode(str(result.value), "unicode_escape", errors="replace").strip()
    if not result.done:
        return {"ok": False, "message": result_value, "code": code}

    return result_value


TEMPLATE = "[{severity} {code}] {file}:{line}:{column}\n{message}"


@mcp.tool
async def python_staticcheck_checks(path: str, checks: str | list[str] | None = None):
    """
    Run staticcheck on a specified Go file or directory and return formatted findings.
    Accepts an absolute path and optional check filter (comma-separated string or list).
    """
    if not isinstance(path, str) or not Path(path).is_absolute():
        return {"ok": False, "message": "`path` must be an absolute string path.", "code": None, "path": path}

    args = _build_checks_cmd(path, checks)
    result = await _run_staticcheck(*args, style="json")
    if not result.done:
        res_val = result.value
        if isinstance(result.value, str):
            res_val = result.value.replace("\\\\", "\\")
        return {"ok": False, "error": res_val or UNKNOWN_ERROR}

    issues = _parse_staticcheck_json(result.value, fallback_path=path)
    return {"ok": True, "issues": [issue.__dict__ for issue in issues]}


def main():
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
