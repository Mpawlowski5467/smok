"""Extension tools and lifecycle; the agent loop remains provider- and extension-neutral."""

import json

from smok.extensions.catalog import Catalog
from smok.extensions.mcp import MCP
from smok.extensions.review import review_diff
from smok.extensions.web import Web
from smok.settings import ProjectSettings
from smok.tools.files import ToolError
from smok.types import ToolSpec


def object_schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


STRING = {"type": "string", "minLength": 1, "maxLength": 8000}
SPECS = [
    ToolSpec(
        "list_extensions",
        "List installed skills, commands, plugins, recipes, hooks, and MCP servers.",
        object_schema({}),
    ),
    ToolSpec(
        "load_skill",
        "Load a relevant skill's full instructions on demand by its catalog name.",
        object_schema({"name": STRING}, ["name"]),
    ),
    ToolSpec(
        "reload_extensions",
        "Reload .smok-extensions after editing its files; validate atomically. "
        "Disconnects MCP servers; reconnect explicitly. Does not execute extension code.",
        object_schema({}),
    ),
    ToolSpec(
        "mcp_connect",
        "Connect to a configured MCP server (host process or HTTP). Requires approval; "
        "returns namespaced tools for subsequent calls.",
        object_schema({"server": STRING}, ["server"]),
        True,
    ),
    ToolSpec(
        "mcp_disconnect",
        "Close a configured MCP connection and remove its tools.",
        object_schema({"server": STRING}, ["server"]),
    ),
    ToolSpec(
        "web_fetch",
        "Fetch an HTTP(S) text/HTML/JSON page. No JavaScript; public addresses by default. "
        "Requires approval and returns source URL and text.",
        object_schema({"url": STRING}, ["url"]),
        True,
    ),
    ToolSpec(
        "web_search",
        "Search with configured Brave API or SearXNG. Requires approval and search "
        "configuration. Returns linked results; verify with web_fetch.",
        object_schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 600},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            ["query"],
        ),
        True,
    ),
    ToolSpec(
        "review_diff",
        "Collect uncommitted Git changes, or committed branch changes from the "
        "merge-base with base to HEAD. Does not execute tests or edit files.",
        object_schema({"base": {"type": "string", "minLength": 1, "maxLength": 200}}),
    ),
]


class Extensions:
    def __init__(self, workspace, settings):
        self.workspace = workspace
        self.catalog = Catalog(workspace)
        self.mcp = MCP(workspace.root, settings.data)
        self.web = Web(settings.data)
        self.generation = 0

    def specs(self, mode):
        return SPECS + self.mcp.specs(mode)

    def listing(self):
        return self.catalog.listing() | {
            "mcp_servers": self.mcp.listing(),
            "generation": self.generation,
        }

    def prompt(self):
        servers = self.mcp.listing()
        return self.catalog.prompt() + (
            "\nConfigured MCP servers (connect with mcp_connect when relevant):\n"
            + json.dumps(servers)
            if servers
            else ""
        )

    def check_mode(self, name, args, mode):
        if mode != "plan":
            return
        if name in self.mcp.tools and not self.mcp.readonly(name):
            raise ToolError(
                "Plan mode blocks MCP tools unless the user explicitly lists them "
                "in that server's read_only configuration."
            )
        if name == "mcp_connect" and not self.mcp.config(args["server"]).get("read_only"):
            raise ToolError("Plan mode blocks MCP connections without configured read_only tools.")

    def approval(self, name, args):
        if name == "mcp_connect" or name in self.mcp.tools:
            return self.mcp.approval(name, args)
        if name.startswith("web_"):
            return {"web": self.web.config}
        return {}

    async def reload(self):
        # Construct/validate everything first. Invalid reloads leave the live catalog intact.
        settings = ProjectSettings(self.workspace.root)
        catalog = Catalog(self.workspace)
        mcp = MCP(self.workspace.root, settings.data)
        web = Web(settings.data)
        await self.mcp.close()
        self.catalog, self.mcp, self.web = catalog, mcp, web
        self.generation += 1
        return json.dumps(self.listing(), ensure_ascii=False)

    async def execute(self, name, args):
        match name:
            case "list_extensions":
                return json.dumps(self.listing(), ensure_ascii=False)
            case "load_skill":
                return self.catalog.render("skills", args["name"])[0]
            case "reload_extensions":
                return await self.reload()
            case "web_fetch":
                return await self.web.fetch(**args)
            case "web_search":
                return await self.web.search(**args)
            case "review_diff":
                return await review_diff(self.workspace, **args)
            case _:
                return await self.mcp.execute(name, args)

    async def close(self):
        await self.mcp.close()
