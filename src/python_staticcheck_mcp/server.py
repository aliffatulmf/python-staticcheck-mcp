from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Iterable
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent

MCP_NAME = "python-staticcheck-mcp"

mcp = FastMCP(name=MCP_NAME)


async def _invoke_staticcheck(args: list[str], style: str = "text") -> dict:
    bin_path = shutil.which("staticcheck")
    if not bin_path:
        return {"success": False, "output": "", "error": "staticcheck binary not found"}

    cmd_args = [bin_path, "-f", style, *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        output_str = stdout.decode(errors="replace").strip() if stdout else ""
        error_str = stderr.decode(errors="replace").strip() if stderr else ""

        if proc.returncode not in (0, 1):
            error_msg = error_str or "unknown error"
            return {"success": False, "output": "", "error": error_msg}

        return {"success": True, "output": output_str, "error": ""}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e) or "unknown exception"}


def _parse_staticcheck_json(output: str, fallback_path: str) -> list[dict]:
    results: list[dict] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj: dict = json.loads(line)
        except json.JSONDecodeError:
            continue

        severity = (str(obj.get("severity") or "")).upper() or "UNKNOWN"
        code = obj.get("code") or "UNKNOWN"

        loc: dict = obj.get("location", {}) or {}
        path = loc.get("file") or fallback_path
        line_num = int(loc.get("line") or 0)
        column_num = int(loc.get("column") or 0)

        message: str = str(obj.get("message") or "").strip()

        results.append(
            {
                "severity": severity,
                "code": code,
                "file": path,
                "line": line_num,
                "column": column_num,
                "message": message,
            }
        )

    return results


def _build_args(path: str, checks: str | Iterable[str] | None) -> list[str]:
    args: list[str] = []
    if checks:
        if not isinstance(checks, str):
            checks = ",".join(checks)
        args.extend(["-checks", checks])

    abs_path = str(Path(path).resolve())
    args.append(abs_path)
    return args


def _error_result(message: str, code: str | None = None) -> ToolResult:
    return ToolResult(
        content=TextContent(type="text", text=message),
        structured_content={
            "is_error": True,
            "code": code,
            "message": message,
        },
    )


@mcp.tool
async def python_staticcheck_explain(code: str | None = None) -> ToolResult:
    """
    Return the official staticcheck explanation for a specific check code.
    Accepts a staticcheck identifier (e.g., "SA4006") and invokes staticcheck -explain <check>.
    """
    if code is None:
        return _error_result("error: check code is required.").to_mcp_result()

    result = await _invoke_staticcheck(["-explain", code])
    if not result["success"]:
        return _error_result(f"error executing staticcheck: {result['error']}", code).to_mcp_result()

    text = result["output"].strip()
    return ToolResult(
        content=TextContent(type="text", text=text),
        structured_content={
            "is_error": False,
            "code": code,
            "explanation": text,
        },
    ).to_mcp_result()


TEMPLATE = "[{severity} {code}] {file}:{line}:{column}\n{message}"


@mcp.tool
async def python_staticcheck_checks(path: str, checks: str | Iterable[str] | None = None) -> ToolResult:
    """
    Run staticcheck on a specified Go file or directory and return formatted findings.
    Accepts an absolute path and optional check filter (comma-separated string or list).
    """
    if not Path(path).is_absolute():
        return _error_result("error: path must be an absolute path.").to_mcp_result()

    args = _build_args(path, checks)
    result = await _invoke_staticcheck(args, style="json")
    if not result["success"]:
        return _error_result(f"error executing staticcheck: {result['error']}").to_mcp_result()

    issues = _parse_staticcheck_json(result["output"], path)
    if issues:
        first_issue = issues[0]
        first_issue["is_error"] = False
        content = TEMPLATE.format(**first_issue)
        structured = first_issue
    else:
        content = "no issues found."
        structured = {"is_error": False, "message": content}

    return ToolResult(
        content=TextContent(type="text", text=content),
        structured_content=structured,
    ).to_mcp_result()


def main():
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
