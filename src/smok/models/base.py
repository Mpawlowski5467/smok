from collections.abc import AsyncIterator
from typing import Protocol

from smok.types import Event, Message, ToolSpec


class ModelError(Exception):
    """A provider failed or produced an incomplete stream."""


class ModelAdapter(Protocol):
    name: str

    def stream(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> AsyncIterator[Event]: ...
