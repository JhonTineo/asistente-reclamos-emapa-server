from tools.base import Tool


class ToolRegistry:
    _tools: dict[str, Tool] = {}
    _role_tools: dict[str, list[str]] = {}

    @classmethod
    def register(cls, tool: Tool, roles: list[str]) -> None:
        cls._tools[tool.name] = tool
        for role in roles:
            if role not in cls._role_tools:
                cls._role_tools[role] = []
            cls._role_tools[role].append(tool.name)

    @classmethod
    def get_tools_for_role(cls, role: str) -> list[Tool]:
        tool_names = cls._role_tools.get(role, [])
        return [cls._tools[name] for name in tool_names]

    @classmethod
    def get_tool(cls, name: str) -> Tool | None:
        return cls._tools.get(name)

    @classmethod
    def get_all_tools(cls) -> dict[str, Tool]:
        return cls._tools.copy()

    @classmethod
    def clear(cls) -> None:
        cls._tools.clear()
        cls._role_tools.clear()
