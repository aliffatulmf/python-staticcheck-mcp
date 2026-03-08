from pydantic import BaseModel

UNKNOWN_ERROR = "unknown error"
UNKNOWN_EXCEPTION = "unknown exception"


class Issue(BaseModel):
    severity: str | None = None
    code: str | None = None
    file: str | None = None
    line: int | None = None
    column: int | None = None
    message: str | None = None


class Value(BaseModel):
    done: bool
    value: str


class ExplainResult(BaseModel):
    ok: bool
    value: str | None = None
    message: str | None = None
    code: str | None = None

    def model_dump(self) -> dict:  # type: ignore[override]
        if self.ok:
            return {"ok": True, "value": self.value}
        return {"ok": False, "message": self.message, "code": self.code}


class AnalysisResult(BaseModel):
    ok: bool
    issues: list[Issue] | None = None
    message: str | None = None
    error: str | None = None
    path: str | None = None
    code: str | None = None

    def model_dump(self) -> dict:  # type: ignore[override]
        if self.ok:
            return {"ok": True, "issues": [issue.model_dump() for issue in (self.issues or [])]}
        result: dict = {"ok": False}
        if self.message:
            result["message"] = self.message
            result["code"] = None
        if self.error:
            result["error"] = self.error
        if self.path is not None:
            result["path"] = self.path
            result["code"] = None
        return result
