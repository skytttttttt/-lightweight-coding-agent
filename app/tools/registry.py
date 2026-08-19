"""工具注册中心：统一注册 6 个工具及 OpenAI tool calling schema。"""
from __future__ import annotations

from typing import Callable, Optional

from app.security.sandbox import Sandbox

ToolFunc = Callable[..., str]


class Tool:
    def __init__(self, name: str, description: str, parameters: dict, fn: ToolFunc):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.fn = fn

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, sandbox: Sandbox):
        self.sandbox = sandbox
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def execute(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"[error] 未知工具: {name}"
        try:
            return tool.fn(self.sandbox, **args)
        except TypeError as e:
            return f"[error] 工具 {name} 参数错误: {e}"
        except Exception as e:  # noqa: BLE001
            return f"[error] 工具 {name} 执行异常: {e}"


def build_registry(sandbox: Sandbox) -> ToolRegistry:
    from app.tools.command import run_command
    from app.tools.edit import edit_file
    from app.tools.files import list_files, read_file, write_file
    from app.tools.git import git_diff
    from app.tools.search import search_code

    registry = ToolRegistry(sandbox)

    registry.register(Tool(
        name="list_files",
        description="列出 workspace 内指定目录下的文件（不递归）。path 默认 '.'。",
        parameters={"type": "object", "properties": {
            "path": {"type": "string", "description": "workspace 内相对路径，默认 '.'"}},
            "required": []},
        fn=list_files,
    ))

    registry.register(Tool(
        name="read_file",
        description="读取 workspace 内文本文件，支持 offset/limit 分页。",
        parameters={"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径（workspace 内）"},
            "offset": {"type": "integer", "description": "起始行（0 基）"},
            "limit": {"type": "integer", "description": "读取行数"}},
            "required": ["path"]},
        fn=read_file,
    ))

    registry.register(Tool(
        name="search_code",
        description="在 workspace 内递归搜索包含指定文本的代码行。",
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "要搜索的文本"},
            "path": {"type": "string", "description": "搜索根目录（workspace 内），默认 '.'"},
            "file_patterns": {"type": "array", "items": {"type": "string"},
                              "description": "文件名 glob，如 ['*.py']"},
            "case_sensitive": {"type": "boolean", "description": "是否区分大小写"}},
            "required": ["query"]},
        fn=search_code,
    ))

    registry.register(Tool(
        name="edit_file",
        description="在 workspace 内文件执行精确字符串替换。old_text 需唯一匹配。",
        parameters={"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径（workspace 内）"},
            "old_text": {"type": "string", "description": "要被替换的原文"},
            "new_text": {"type": "string", "description": "替换后的新文本"},
            "replace_all": {"type": "boolean", "description": "匹配多处时是否全部替换"}},
            "required": ["path", "old_text", "new_text"]},
        fn=edit_file,
    ))

    registry.register(Tool(
        name="write_file",
        description="在 workspace 内创建新文件或覆盖已有文件的完整内容（配合 edit_file 用于局部修改）。禁止用于写 workspace 之外。",
        parameters={"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径（workspace 内）"},
            "content": {"type": "string", "description": "文件完整内容"}},
            "required": ["path", "content"]},
        fn=write_file,
    ))

    registry.register(Tool(
        name="run_command",
        description="在受限工作目录执行项目测试/构建命令（pytest、python、npm test 等）。危险命令被拒绝。",
        parameters={"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "workdir": {"type": "string", "description": "'project' 或 workspace 内相对路径，默认 'project'"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 60"}},
            "required": ["command"]},
        fn=run_command,
    ))

    registry.register(Tool(
        name="git_diff",
        description="查看项目工作区 git diff（不含 path 时查看全部改动），检查修改是否合规。",
        parameters={"type": "object", "properties": {
            "path": {"type": "string", "description": "可选，限定查看某文件 diff"}},
            "required": []},
        fn=git_diff,
    ))

    return registry
