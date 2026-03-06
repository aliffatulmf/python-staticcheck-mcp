from dataclasses import dataclass

UNKNOWN_ERROR = "unknown error"
UNKNOWN_EXCEPTION = "unknown exception"


@dataclass(frozen=True)
class Issue:
    severity: str | None = None
    code: str | None = None
    file: str | None = None
    line: int | None = None
    column: int | None = None
    message: str | None = None


@dataclass(frozen=True)
class ExecResult:
    done: bool
    value: any
