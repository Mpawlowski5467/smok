"""Tool implementations; the registry is loaded lazily to avoid import cycles."""

__all__ = ["ToolRegistry"]


def __getattr__(name):
    if name == "ToolRegistry":
        from smok.tools.registry import ToolRegistry

        return ToolRegistry
    raise AttributeError(name)
