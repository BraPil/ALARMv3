"""ALARMv3 MCP prompts — 2 guided workflows."""

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:

    @mcp.prompt()
    def analyze_codebase(source_path: str = "") -> str:
        """Guided workflow to analyze a legacy codebase end-to-end."""
        hint = f" at `{source_path}`" if source_path else ""
        return f"""You are analyzing a legacy codebase{hint} using ALARMv3.

Follow this exact sequence — each step gates the next:

1. **attach_repository("{source_path or '/path/to/repo'}")** — bind to the source
2. **confirm_guardrails(session_id)** — confirm read-only (mandatory gate)
3. **start_full_mapping(session_id)** — begin file discovery (background)
4. **get_job_status(job_id)** — poll every 5s until status="complete"
5. **run_analysis(session_id)** — parse ASTs + build dependency graph (background)
6. **get_job_status(job_id)** — poll until complete
7. **generate_recommendations(session_id)** — synthesize recommendations with Claude

After each step, check `session://current` to confirm state progression.
After step 7, read `recommendations://latest` for the full list.

⚠️ The source repository is read-only. Never attempt to modify it."""

    @mcp.prompt()
    def explain_component(component_path: str) -> str:
        """Deep-dive explanation of a specific file or module in the codebase."""
        return f"""Explain the component at `{component_path}` in the attached legacy codebase.

Use the available resources to answer:

1. Check `manifest://files` — confirm the file exists and its language/size
2. Check `recommendations://latest` — any recommendations targeting this file?
3. From the analysis data, explain:
   - **Purpose**: what does this component do?
   - **Dependencies**: what does it import/include, and what imports it?
   - **Complexity**: size, structure, notable patterns
   - **Modernization priority**: based on recommendations, how urgent is attention here?

Be specific. Cite file paths and line numbers where the analysis provides them."""
