import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


try:
    import fastmcp  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("fastmcp")

    class FastMCP:
        def __init__(self, name: str):
            self.name = name

        def tool(self, func):
            return func

        def run(self, *args, **kwargs):
            return None

    stub.FastMCP = FastMCP
    sys.modules["fastmcp"] = stub
