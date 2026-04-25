"""MCP server for GitHub Issue Tool."""

from __future__ import annotations

import sys
from pathlib import Path

from mcp.server.lowlevel import Server
from mcp.types import CallToolResult, TextContent, Tool

from src.config_cache import ConfigCache
from src.gather import gather_config
from src.gh_executor import execute_issues
from src.validator import validate_issues


server = Server("github-issue-tool")
config_cache = ConfigCache()
DEFAULT_CONFIG_DIR = Path("./config")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="gather-config",
            description="Gather repo metadata from GitHub into config files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "GitHub repo (owner/repo-name)"},
                    "config_dir": {"type": "string", "description": "Config directory"},
                },
                "required": ["repo"],
            },
        ),
        Tool(
            name="create-issues",
            description="Create issues from JSON input.",
            inputSchema={
                "type": "object",
                "properties": {
                    "issues": {"type": "array", "description": "Issue objects"},
                    "config_dir": {"type": "string"},
                    "dry_run": {"type": "boolean"},
                },
                "required": ["issues"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> CallToolResult:
    """Handle tool calls."""
    try:
        if name == "gather-config":
            return await _tool_gather_config(arguments)
        elif name == "create-issues":
            return await _tool_create_issues(arguments)
        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: {name}")],
                isError=True,
            )
    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")],
            isError=True,
        )


async def _tool_gather_config(arguments: dict) -> CallToolResult:
    """Gather config tool."""
    repo = arguments.get("repo")
    if not repo:
        raise ValueError("repo is required")

    config_dir = Path(arguments.get("config_dir", DEFAULT_CONFIG_DIR))
    config_dir.mkdir(parents=True, exist_ok=True)

    try:
        gather_config(repo=repo, config_dir=config_dir)
        config_cache.refresh(config_dir)
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"✓ Config gathered from {repo}\nCache refreshed.",
                )
            ]
        )
    except Exception as e:
        raise ValueError(f"Failed to gather config: {str(e)}")


async def _tool_create_issues(arguments: dict) -> CallToolResult:
    """Create issues tool."""
    issues_data = arguments.get("issues")
    if not issues_data:
        raise ValueError("issues is required")

    config_dir = Path(arguments.get("config_dir", DEFAULT_CONFIG_DIR))
    dry_run = arguments.get("dry_run", False)

    try:
        config = config_cache.get(config_dir)
    except Exception as e:
        raise ValueError(f"Config not found. Run gather-config first.\nError: {str(e)}")

    issue_set_data = {"issues": issues_data} if isinstance(issues_data, list) else issues_data

    # Validate
    validation_result = validate_issues(issue_set_data, config, check_duplicates=True)
    if not validation_result.is_valid:
        error_msg = "Validation errors:\n"
        for err in validation_result.errors:
            path_str = " → ".join(err.path) if err.path else err.issue_id
            error_msg += f"  • [{path_str}] {err.field}: {err.message}\n"
        raise ValueError(error_msg)

    # Execute
    result = execute_issues(data=issue_set_data, config=config, dry_run=dry_run)
    
    output = "Issues created:\n"
    for created in result.created_issues:
        output += f"  • {created.title} (#{created.number})\n"
    
    if result.skipped_issues:
        output += "Skipped (duplicates):\n"
        for skipped in result.skipped_issues:
            output += f"  • {skipped}\n"
    
    return CallToolResult(content=[TextContent(type="text", text=output)])


def main() -> None:
    """Run MCP server."""
    import asyncio
    asyncio.run(server.run(sys.stdin.buffer, sys.stdout.buffer))


if __name__ == "__main__":
    main()
