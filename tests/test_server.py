import json
import pathlib
import subprocess
from unittest.mock import patch

from staticcheck_mcp import server


def test_find_go_files_non_recursive(tmp_path):
    pkg_dir = tmp_path / "pkg"
    nested_dir = pkg_dir / "nested"
    pkg_dir.mkdir()
    nested_dir.mkdir()

    main_go = pkg_dir / "main.go"
    nested_go = nested_dir / "nested.go"
    readme_txt = pkg_dir / "readme.txt"

    main_go.write_text("package main\n")
    nested_go.write_text("package nested\n")
    readme_txt.write_text("x\n")

    found_files = server.find_go_files([str(pkg_dir)], recursive=False)

    assert found_files == [str(main_go.resolve())]


def test_find_go_files_recursive(tmp_path):
    root = tmp_path / "root"
    child = root / "a" / "b"
    child.mkdir(parents=True)
    one = root / "one.go"
    two = child / "two.go"
    one.write_text("package root\n")
    two.write_text("package b\n")

    found = server.find_go_files([str(root)], recursive=True)

    assert found == sorted([str(one.resolve()), str(two.resolve())])


def test_find_go_files_in_dir_permission_error(monkeypatch):
    path = pathlib.Path(".")

    def raise_permission(self):
        raise PermissionError()

    monkeypatch.setattr(pathlib.Path, "iterdir", raise_permission)
    result = server._find_go_files_in_dir(path, recursive=False)
    assert result == set()


def test_find_go_files_oserror(monkeypatch):
    path = pathlib.Path(".")

    def raise_oserror(self):
        raise OSError()

    monkeypatch.setattr(pathlib.Path, "expanduser", raise_oserror)
    found = server.find_go_files([str(path)], recursive=False)
    assert found == []


def test_parse_staticcheck_ignores_invalid_lines():
    valid = {
        "location": {"file": "x\\y.go", "line": 7, "column": 3},
        "message": "  bad   spacing  ",
        "code": "SA4006",
    }
    stdout = "\n".join(["not-json", json.dumps(valid), "123"])

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["staticcheck", "-f", "json", "test.go"], returncode=0, stdout=stdout, stderr=""
        )

        result = server.analyze(["staticcheck", "-f", "json"], ["test.go"])

    assert len(result.findings) == 1
    assert result.findings[0].file == "x/y.go"
    assert result.findings[0].message == "bad spacing"
    assert result.findings[0].code == "SA4006"


def test_analyze_missing_binary(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda _: None)

    result = server.analyze(["staticcheck", "-f", "json"], ["x.go"])

    assert result.success is False
    assert any("missing" in item.message for item in result.findings)


def test_analyze_no_findings(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda _: "staticcheck")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["staticcheck", "-f", "json", "a.go"], returncode=0, stdout="", stderr=""
        )

        result = server.analyze(["staticcheck", "-f", "json"], ["a.go"])

    assert result.success is True
    assert result.findings == []


def test_analyze_subprocess_error(monkeypatch):
    def dummy_run(*a, **kw):
        raise subprocess.SubprocessError("fail")

    monkeypatch.setattr(server.subprocess, "run", dummy_run)
    result = server.analyze(["staticcheck", "-f", "json"], ["a.go"])
    assert result.success is False
    assert any("Failed to run" in item.message for item in result.findings)


def test_checks_returns_dict(monkeypatch):
    monkeypatch.setattr(server, "find_go_files", lambda paths, recursive: ["a.go"])
    monkeypatch.setattr(
        server,
        "analyze",
        lambda cmd, targets: server.AnalysisResult(success=True, findings=[]),
    )

    result = server.checks(paths=["."], recursive=False)

    assert json.loads(result) == {"success": True, "findings": []}


def test_build_staticcheck_cmd_variants():
    assert server.build_cmd(None) == ["staticcheck", "-f", "json"]
    assert server.build_cmd(["A", "B"]) == ["staticcheck", "-f", "json", "-checks", "A,B"]
    assert server.build_cmd("A") == ["staticcheck", "-f", "json", "-checks", "A"]


def test_main_uses_sse_transport(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setenv("STATICCHECK_MCP_TRANSPORT", "sse")
    monkeypatch.setenv("STATICCHECK_MCP_PORT", "8088")
    monkeypatch.setattr(server.mcp, "run", fake_run)

    server.main()

    _, kwargs = calls[0]
    assert kwargs["transport"] == "stdio"


def test_main_uses_stdio_transport(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.delenv("STATICCHECK_MCP_TRANSPORT", raising=False)
    monkeypatch.setattr(server.mcp, "run", fake_run)

    server.main()

    _, kwargs = calls[0]
    assert kwargs["transport"] == "stdio"


def test_main_direct(monkeypatch):
    called = {}

    def fake_run(*args, **kwargs):
        called["run"] = True

    monkeypatch.setattr(server.mcp, "run", fake_run)
    server.main()
    assert called["run"] is True
