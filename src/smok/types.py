"""Provider-neutral conversation blocks and serializable core events."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from smok.images import Image


@dataclass(frozen=True)
class Text:
    text: str
    type: Literal["text"] = "text"


class RuntimeHint(Text):
    """Transient request text; cache boundaries must precede this changing note."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # Keep raw JSON so malformed calls can receive a useful tool error.
    type: Literal["tool_call"] = "tool_call"


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: list[Text | Image | ToolCall | ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    requires_approval: bool = False


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def messages_to_data(messages: list[Message], *, images=True) -> list[dict]:
    result = [asdict(message) for message in messages]
    if not images:
        for message in result:
            message["content"] = [
                {
                    "type": "text",
                    "text": "[User image omitted from text handoff; ask for it again if needed.]",
                }
                if block["type"] == "image"
                else block
                for block in message["content"]
            ]
    return result


def messages_from_data(data) -> list[Message]:
    if not isinstance(data, list) or len(data) > 10000:
        raise ValueError("Invalid session message list.")
    messages = []
    pending = set()
    for item in data:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise ValueError("Invalid session message.")
        role, blocks = item["role"], item["content"]
        if (
            not isinstance(role, str)
            or role not in {"user", "assistant"}
            or not isinstance(blocks, list)
            or not blocks
        ):
            raise ValueError("Invalid session role or content.")
        parsed = []
        if not all(isinstance(b, dict) for b in blocks):
            raise ValueError("Invalid session block.")
        if pending and (role != "user" or any(b.get("type") != "tool_result" for b in blocks)):
            raise ValueError("Session contains unmatched tool calls.")
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError("Invalid session block.")
            kind = block.get("type")
            if kind == "text" and set(block) == {"type", "text"} and isinstance(block["text"], str):
                parsed.append(Text(block["text"]))
            elif (
                kind == "image" and role == "user" and set(block) == {"type", "media_type", "data"}
            ):
                parsed.append(Image(block["media_type"], block["data"]))
            elif (
                kind == "tool_call"
                and role == "assistant"
                and set(block) == {"type", "id", "name", "arguments"}
            ):
                if (
                    not all(isinstance(block[k], str) for k in ("id", "name", "arguments"))
                    or not block["id"]
                    or block["id"] in pending
                ):
                    raise ValueError("Invalid saved tool call.")
                parsed.append(ToolCall(block["id"], block["name"], block["arguments"]))
                pending.add(block["id"])
            elif (
                kind == "tool_result"
                and role == "user"
                and set(block) == {"type", "tool_call_id", "content", "is_error"}
            ):
                if (
                    not isinstance(block["tool_call_id"], str)
                    or block["tool_call_id"] not in pending
                    or not isinstance(block["content"], str)
                    or not isinstance(block["is_error"], bool)
                ):
                    raise ValueError("Invalid saved tool result.")
                pending.remove(block["tool_call_id"])
                parsed.append(
                    ToolResult(block["tool_call_id"], block["content"], block["is_error"])
                )
            else:
                raise ValueError("Unsupported saved message block.")
        if role == "user" and pending:
            raise ValueError("Session contains an incomplete tool-result group.")
        messages.append(Message(role, parsed))
    if pending:
        raise ValueError("Session ends with unmatched tool calls.")
    return messages
