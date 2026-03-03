from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel, model_validator

MCP_NAME = "staticcheck-mcp"

mcp = FastMCP(name=MCP_NAME)


class AnalysisResult(BaseModel):
    success: bool
    findings: list[Finding]


class Finding(BaseModel):
    file: str
    message: str
    line: int | None = None
    column: int | None = None
    code: str | None = None

    @model_validator(mode="before")
    @classmethod
    def clean_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            file_path = data.get("file")
            if isinstance(file_path, str):
                data["file"] = file_path.replace("\\", "/")
        return data


def _find_go_files_in_dir(path: Path, recursive: bool) -> set[str]:
    targets = set()
    if recursive:
        for root, _, file_names in os.walk(path):
            for file_name in file_names:
                if file_name.endswith(".go"):
                    targets.add(str((Path(root) / file_name).resolve()))
    else:
        try:
            for child in path.iterdir():
                if child.is_file() and child.suffix == ".go":
                    targets.add(str(child.resolve()))
        except Exception:
            pass
    return targets


def find_go_files(paths: list[str], recursive: bool) -> list[str]:
    targets = set()
    for raw_path in paths:
        try:
            path = Path(raw_path).expanduser().resolve()
        except Exception:
            sys.stderr.write(f"Warning: Skipping invalid path '{raw_path}'\n")
            continue
        if path.is_file() and path.suffix == ".go":
            targets.add(str(path))
        elif path.is_dir():
            targets.update(_find_go_files_in_dir(path, recursive))
    return sorted(targets)


def _parse_staticcheck_output(output: str) -> list[Finding]:
    findings = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            location = payload.get("location", {})
            file = str(location.get("file", "")).replace("\\", "/")
            line_num = location.get("line")
            column = location.get("column")
            message = " ".join(str(payload.get("message", "")).split())
            code = payload.get("code")
            findings.append(
                Finding(
                    file=file,
                    line=line_num,
                    column=column,
                    message=message,
                    code=code,
                )
            )
    return findings


def build_cmd(checks: str | list[str] | None = None) -> list[str]:
    cmd = ["staticcheck", "-f", "json"]
    if checks:
        if isinstance(checks, list):
            checks = ",".join(checks)
        cmd.extend(["-checks", checks])
    return cmd


def analyze(cmd: list[str], targets: list[str]):
    if not targets:
        return AnalysisResult(success=True, findings=[])

    tool = cmd[0]
    if shutil.which(tool) is None:
        return AnalysisResult(
            success=False,
            findings=[
                Finding(file="", message=f"Required tool '{tool}' is missing. Install it and try again."),
            ],
        )

    try:
        full_cmd = cmd + targets
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=30)

        findings = _parse_staticcheck_output(result.stdout)
        return AnalysisResult(success=True, findings=findings)

    except Exception as e:
        return AnalysisResult(
            success=False,
            findings=[
                Finding(file="", message=f"Failed to run {tool}: {str(e)}"),
            ],
        )


@mcp.tool(
    name="checks",
    description="Run staticcheck on specified files or directories",
    meta={"version": "1.0.0"},
)
def checks(paths: list[str], recursive: bool = False, checks: str | list[str] | None = None):
    targets = find_go_files(paths, recursive=recursive)
    cmd = build_cmd(checks)
    result = analyze(cmd=cmd, targets=targets)
    return result.model_dump_json(indent=2)


def main() -> None:
    print(f"{MCP_NAME}: status=running", file=sys.stderr)
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
