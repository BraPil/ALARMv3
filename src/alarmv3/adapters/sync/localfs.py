"""LocalFS sync adapter — reads from local filesystem, writes to artifact dir."""

from pathlib import Path
from typing import Iterator

from .base import SyncAdapter


class LocalFSAdapter(SyncAdapter):

    def __init__(self, root: Path):
        self._root = root.resolve()

    def read_file(self, path: str) -> bytes:
        return (self._root / path).read_bytes()

    def iter_files(self, root: str = "") -> Iterator[str]:
        base = (self._root / root) if root else self._root
        for f in base.rglob("*"):
            if f.is_file():
                yield str(f.relative_to(self._root))

    def write_artifact(self, path: str, content: bytes) -> None:
        target = self._root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def exists(self, path: str) -> bool:
        return (self._root / path).exists()
