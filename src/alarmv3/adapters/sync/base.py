"""SyncAdapter interface — core engine uses this, never concrete implementations."""

from abc import ABC, abstractmethod
from typing import Iterator


class SyncAdapter(ABC):
    """Abstract interface for reading from source and writing artifacts."""

    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Read a file from the source zone."""
        ...

    @abstractmethod
    def iter_files(self, root: str = "") -> Iterator[str]:
        """Yield relative file paths under root."""
        ...

    @abstractmethod
    def write_artifact(self, path: str, content: bytes) -> None:
        """Write content to the artifact zone."""
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Return True if path exists."""
        ...
