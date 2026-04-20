"""ALARMv3 MCP server entry point.

Phase 1: stdio transport (Claude Code connects directly, no port management).
Phase 3+: HTTP transport for standalone REST API self-service.

Register with Claude Code by adding to .mcp.json:
  "alarmv3": {
    "command": "uv",
    "args": ["run", "alarmv3-mcp"],
    "env": { "ALARMV3_WORKSPACE": "${workspaceFolder}" }
  }
"""

from mcp.server.fastmcp import FastMCP

from .tools import register_tools
from .resources import register_resources
from .prompts import register_prompts

mcp = FastMCP(
    "alarmv3",
    instructions="""ALARMv3 — Legacy Code Modernization Assistant

Use these tools in order:
1. attach_repository(source_path)      — bind to the legacy codebase
2. confirm_guardrails(session_id)      — mandatory safety gate (read-only confirmed)
3. start_full_mapping(session_id)      — discover all files (background job)
4. get_job_status(job_id)              — poll until mapping complete
5. run_analysis(session_id)            — parse dependencies + complexity (background job)
6. get_job_status(job_id)              — poll until analysis complete
7. generate_recommendations(session_id) — produce prioritized recommendations

Read resources anytime:
- session://current        — current session state
- manifest://files         — discovered file list
- recommendations://latest — full recommendation set

The source repository is READ-ONLY. It will never be modified.""",
)

register_tools(mcp)
register_resources(mcp)
register_prompts(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
