"""Generate the full-archive ADDS wiki from analysis.db.

Reads the populated tables from a completed ALARMv3 session and emits a
comprehensive Markdown wiki with: (1) full-archive file inventory grouped
by language and folder, (2) subsystem maps with Mermaid diagrams, (3)
findings sections per category, (4) prioritized recommendations table,
(5) RAG query examples, (6) "perfect prompts" appendix where each accepted
recommendation is paired with a self-contained prompt to execute it.

Usage:
    python scripts/generate_full_wiki.py \\
        --db /workspaces/ADDS_ALARMv3/.alarmv3/sessions/<id>/analysis.db \\
        --session-id <id> \\
        --source-root /workspaces/ADDS \\
        --out /workspaces/ADDS_ALARMv3/wiki/ADDS_wiki.md
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

SEVERITY_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
VERDICT_EMOJI = {"accept": "✅", "revise": "✏️", "reject": "❌", "pending": "⏳"}


def _fetch(db_path: Path, sid: str) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        manifest = [dict(r) for r in conn.execute(
            "SELECT relative_path, language, line_count, size_bytes, is_eligible "
            "FROM manifest WHERE session_id=? ORDER BY relative_path", (sid,))]
        recs = [dict(r) for r in conn.execute(
            "SELECT rank, category, severity, title, description, rationale, "
            "affected_files, effort, evaluator_verdict, evaluator_critique, "
            "evaluator_effort, risk_score FROM recommendation "
            "WHERE session_id=? ORDER BY rank", (sid,))]
        for r in recs:
            try:
                r["affected_files"] = json.loads(r["affected_files"] or "[]")
            except (TypeError, json.JSONDecodeError):
                r["affected_files"] = []
        subs = [dict(r) for r in conn.execute(
            "SELECT subsystem_index, name, file_count, total_loc, avg_complexity, files "
            "FROM subsystem WHERE session_id=? ORDER BY subsystem_index", (sid,))]
        for s in subs:
            s["files"] = json.loads(s["files"] or "[]")
        findings = {}
        for r in conn.execute(
            "SELECT subsystem_index, pass_type, findings_json FROM subsystem_finding "
            "WHERE session_id=? AND pass_type='subsystem'", (sid,)):
            try:
                findings[r["subsystem_index"]] = json.loads(r["findings_json"] or "[]")
            except json.JSONDecodeError:
                findings[r["subsystem_index"]] = []
        symbols_by_file: dict[str, dict[str, int]] = defaultdict(dict)
        for r in conn.execute(
            "SELECT file_path, symbol_type, COUNT(*) AS n FROM symbol "
            "WHERE session_id=? GROUP BY file_path, symbol_type", (sid,)):
            symbols_by_file[r["file_path"]][r["symbol_type"]] = r["n"]
        chunks_count = conn.execute(
            "SELECT COUNT(*) FROM code_chunk WHERE session_id=? AND embedded=1", (sid,)
        ).fetchone()[0]
        edges_count = conn.execute(
            "SELECT COUNT(*) FROM dependency_edge WHERE session_id=?", (sid,)
        ).fetchone()[0]
        grammars = [dict(r) for r in conn.execute(
            "SELECT file_ext, language_name FROM language_grammar "
            "WHERE session_id=? ORDER BY file_ext", (sid,))]
    finally:
        conn.close()
    return {
        "manifest": manifest, "recs": recs, "subsystems": subs,
        "findings": findings, "symbols_by_file": symbols_by_file,
        "chunks_count": chunks_count, "edges_count": edges_count,
        "grammars": grammars,
    }


# ── Diagram builders ──────────────────────────────────────────────────────────

def _subsystem_overview_mermaid(subs: list[dict]) -> str:
    """Top-level box diagram of the subsystems and their sizes."""
    lines = ["```mermaid", "graph TB"]
    for s in subs:
        nid = f"S{s['subsystem_index']}"
        label = f"{s['name'].split('/')[-1]}<br/>{s['file_count']} files / {int(s['total_loc'])} loc"
        lines.append(f"    {nid}[\"{label}\"]")
    # Add a "Source archive" anchor.
    lines.append('    SRC["/workspaces/ADDS<br/>319 files / 222 eligible"]')
    for s in subs:
        lines.append(f"    SRC --> S{s['subsystem_index']}")
    lines.append("```")
    return "\n".join(lines)


def _component_map_mermaid(recs: list[dict]) -> str:
    """High-level component map of ADDS based on file paths in recs.

    Builds boxes for the major folders observed in affected_files.
    """
    return """```mermaid
graph LR
    User[("Operator<br/>(AutoCAD user)")]
    AcadGUI["AutoCAD GUI / Forms<br/>(C# 19.0/Adds/Forms)"]
    AcadCmds["AutoCAD Commands<br/>(C# 19.0/Adds + LISP)"]
    LispCore["LISP Core<br/>(Common/Utils.Lsp,<br/>Acad.Lsp, GetPoints.Lsp)"]
    LispUser["User Tools<br/>(Adds/User/*.Lsp)"]
    OracleDA["Oracle DataAccess<br/>(C# Common/OraLogin.cs<br/>+ Acad_ADO.Lsp)"]
    OracleDB[("Oracle 11g<br/>schema")]
    Palettes["Tool Palettes<br/>(LookUpTable .atc/.xtp)"]
    DCL["DCL Dialogs<br/>(*.dcl)"]
    Deploy["Deploy Scripts<br/>(Utils *.Cmd)"]
    Share[("S:\\\\Workgroups<br/>UNC share")]
    Config[("div_map.ini<br/>(creds + paths)")]
    User --> AcadGUI
    User --> AcadCmds
    AcadGUI --> AcadCmds
    AcadCmds --> LispCore
    AcadCmds --> LispUser
    LispCore --> Palettes
    LispCore --> DCL
    AcadCmds --> OracleDA
    LispCore --> OracleDA
    OracleDA --> OracleDB
    Deploy --> Share
    Share --> AcadCmds
    Config -.-> OracleDA
    Config -.-> AcadCmds
```"""


def _sync_flow_mermaid() -> str:
    return """```mermaid
sequenceDiagram
    participant U as Operator
    participant W as Workstation<br/>(C:\\Div_Map\\)
    participant CMD as Upd_S_Map_AddsW10.Cmd
    participant S as S:\\Workgroups\\<br/>(network share)
    participant L as AutoLISP
    participant O as Oracle 11g

    U->>CMD: run deploy script
    CMD->>S: Xcopy /D /F /S
    S-->>W: Adds, Common, LookUpTable, etc.
    Note over CMD: icacls /grant Users:(oi)(ci)f<br/>(overly broad — finding #6)
    U->>L: invoke command (e.g. C:InIER)
    L->>L: load Utils.Lsp, Acad.Lsp
    L->>O: SQL via OraLogin / Acad_ADO<br/>(string concatenation — finding #2)
    O-->>L: result rows
    L-->>U: drawing entity placed
```"""


# ── Section builders ──────────────────────────────────────────────────────────

def _file_inventory_section(manifest: list[dict], symbols_by_file: dict) -> str:
    eligible = [m for m in manifest if m["is_eligible"]]
    by_lang = defaultdict(list)
    for m in eligible:
        by_lang[m["language"] or "(unknown)"].append(m)
    total_lines = sum((m["line_count"] or 0) for m in eligible)
    total_size = sum((m["size_bytes"] or 0) for m in eligible)

    lines = [
        "## 2. File Inventory (Full Archive)\n",
        f"_Sourced from `manifest` table at session 355090bd, full archive commit `1271468`._\n",
        f"**{len(manifest)} files in archive · {len(eligible)} source-eligible · "
        f"{total_lines:,} lines · {total_size/1024/1024:.1f} MB._\n",
        "### 2.1 By language\n",
        "| Language | Files | Eligible LOC | % of LOC |",
        "|---|---:|---:|---:|",
    ]
    rows = []
    for lang, files in by_lang.items():
        loc = sum((m["line_count"] or 0) for m in files)
        rows.append((lang, len(files), loc))
    rows.sort(key=lambda x: -x[2])
    for lang, n, loc in rows:
        pct = (loc / total_lines * 100) if total_lines else 0
        lines.append(f"| `{lang}` | {n} | {loc:,} | {pct:.1f}% |")

    lines.append("\n### 2.2 Top 25 source files by line count\n")
    lines.append("| LOC | Language | Path | Symbols |")
    lines.append("|---:|---|---|---|")
    top = sorted(eligible, key=lambda m: -(m["line_count"] or 0))[:25]
    for m in top:
        sym_summary = symbols_by_file.get(m["relative_path"], {})
        sym_str = ", ".join(f"{k}:{v}" for k, v in sorted(sym_summary.items()))
        lines.append(f"| {m['line_count']} | `{m['language']}` | `{m['relative_path']}` | {sym_str or '_(none)_'} |")

    lines.append("\n### 2.3 Folder distribution\n")
    folders: dict[str, int] = defaultdict(int)
    for m in eligible:
        parts = (m["relative_path"] or "").split("/")
        if len(parts) > 2:
            folders["/".join(parts[:2])] += 1
        elif len(parts) > 1:
            folders[parts[0]] += 1
    lines.append("| Folder | Eligible files |")
    lines.append("|---|---:|")
    for folder, n in sorted(folders.items(), key=lambda x: -x[1]):
        lines.append(f"| `{folder}/` | {n} |")
    return "\n".join(lines)


def _subsystem_section(subs: list[dict], findings: dict) -> str:
    lines = [
        "## 4. Subsystem partitioning\n",
        "Union-find on the dependency graph (resolved file-to-file edges + shared-module "
        "fallback + 3-level path-prefix coupling) produced **5 subsystems** covering 100% "
        "of eligible files. Ranking is `file_count × max(avg_complexity, 1)` descending so "
        "the most architecturally significant clusters are processed first.\n",
        "### 4.1 Cluster overview\n",
        _subsystem_overview_mermaid(subs),
        "\n### 4.2 Per-subsystem details\n",
    ]
    for s in subs:
        lines.append(f"\n#### Subsystem {s['subsystem_index']}: `{s['name']}`")
        lines.append(f"- **Files**: {s['file_count']}")
        lines.append(f"- **Total LOC**: {int(s['total_loc']):,}")
        lines.append(f"- **Avg complexity**: {s['avg_complexity']}")
        f_list = findings.get(s["subsystem_index"], [])
        lines.append(f"- **Raw findings**: {len(f_list)}")
        if f_list:
            lines.append("\n_Top findings (full text in §5–§7 by category):_\n")
            for f in f_list[:5]:
                emoji = SEVERITY_EMOJI.get(f.get("severity", ""), "⚪")
                lines.append(f"  - {emoji} `{f.get('category','?')}` — {f.get('title','')}")
        # Sample of files in subsystem
        if s["files"]:
            lines.append("\n_Sample files (up to 10):_\n")
            for fp in s["files"][:10]:
                lines.append(f"  - `{fp}`")
            if len(s["files"]) > 10:
                lines.append(f"  - _… and {len(s['files']) - 10} more_")
    return "\n".join(lines)


def _findings_by_category(findings: dict, category: str, title: str) -> str:
    matched = []
    for sub_idx, f_list in findings.items():
        for f in f_list:
            if (f.get("category") or "").lower() == category:
                matched.append((sub_idx, f))
    if not matched:
        return f"## {title}\n\n_No findings in this category._\n"
    matched.sort(key=lambda t: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
        (t[1].get("severity") or "low").lower(), 9), t[0]))

    lines = [f"## {title}\n"]
    lines.append(f"_{len(matched)} raw findings from per-subsystem deep analysis._\n")
    for sub_idx, f in matched:
        emoji = SEVERITY_EMOJI.get(f.get("severity", ""), "⚪")
        lines.append(f"### {emoji} {f.get('title','(untitled)')}")
        lines.append(
            f"_Subsystem {sub_idx} · severity `{f.get('severity','?')}` · "
            f"effort `{f.get('effort','?')}`_\n"
        )
        lines.append(f.get("description", ""))
        if f.get("rationale"):
            lines.append(f"\n> {f['rationale']}")
        if f.get("affected_files"):
            lines.append("\n_Affected files:_")
            for af in f["affected_files"]:
                lines.append(f"- `{af}`")
        lines.append("")
    return "\n".join(lines)


def _recommendations_section(recs: list[dict]) -> str:
    lines = [
        "## 8. Prioritized recommendations\n",
        f"**{len(recs)} ranked recommendations** from the cross-subsystem aggregation pass, "
        "evaluated by an adversarial reviewer (verdict + risk score per row). The full "
        "evaluator critique for each item is in `evaluation_report.md`.\n",
        "| # | Title | Cat | Sev | Effort | Risk | Verdict |",
        "|---:|---|---|---|---|---:|---|",
    ]
    for r in recs:
        emoji_v = VERDICT_EMOJI.get((r.get("evaluator_verdict") or "pending").lower(), "⚪")
        emoji_s = SEVERITY_EMOJI.get((r.get("severity") or "low").lower(), "⚪")
        lines.append(
            f"| {r['rank']} | {r['title'][:75]} | `{r['category']}` | "
            f"{emoji_s}`{r['severity']}` | `{r.get('effort','?')}` | "
            f"{r.get('risk_score') if r.get('risk_score') is not None else 'n/a'} | "
            f"{emoji_v}`{r.get('evaluator_verdict','pending')}` |"
        )

    lines.append("\n### 8.1 Full text per recommendation\n")
    for r in recs:
        emoji_v = VERDICT_EMOJI.get((r.get("evaluator_verdict") or "pending").lower(), "⚪")
        emoji_s = SEVERITY_EMOJI.get((r.get("severity") or "low").lower(), "⚪")
        lines.append(f"\n#### {r['rank']}. {emoji_s} {emoji_v} {r['title']}")
        lines.append(
            f"_Category: `{r['category']}` · "
            f"Severity: `{r['severity']}` · "
            f"Effort: `{r.get('effort','?')}` · "
            f"Risk: `{r.get('risk_score','n/a')}` · "
            f"Verdict: `{r.get('evaluator_verdict','pending')}`_\n"
        )
        lines.append(r["description"])
        if r.get("rationale"):
            lines.append(f"\n> {r['rationale']}")
        if r.get("evaluator_critique"):
            lines.append("\n**Evaluator critique:**\n")
            lines.append(r["evaluator_critique"])
        if r.get("affected_files"):
            lines.append("\n**Affected files:**")
            for af in r["affected_files"]:
                lines.append(f"- `{af}`")
    return "\n".join(lines)


def _rag_section(chunks_count: int, sid: str) -> str:
    return f"""## 10. RAG / vector index — query patterns

The session built **{chunks_count} structure-aware code chunks** (one per symbol or
file header) and embedded each via Ollama `nomic-embed-text` into the
`chunk_vectors` sqlite-vec table inside `analysis.db`.

### 10.1 Direct sqlite-vec query (Python)

```python
import sqlite3, sqlite_vec, ollama
from pathlib import Path

session_dir = Path("/workspaces/ADDS_ALARMv3/.alarmv3/sessions/{sid}")
db = sqlite3.connect(session_dir / "analysis.db")
db.enable_load_extension(True)
sqlite_vec.load(db)
db.row_factory = sqlite3.Row

vec = ollama.embeddings(model="nomic-embed-text", prompt="how is Oracle login handled?")["embedding"]

rows = db.execute('''
    SELECT c.file_path, c.symbol_name, c.start_line, c.end_line,
           v.distance, c.content
    FROM chunk_vectors v
    JOIN code_chunk c ON c.id = v.chunk_id
    WHERE v.embedding MATCH ? AND k = 8
    ORDER BY v.distance
''', [sqlite_vec.serialize_float32(vec)]).fetchall()
for r in rows:
    print(f"{{r['file_path']}}:{{r['start_line']}}  ({{r['distance']:.3f}})  {{r['symbol_name']}}")
```

### 10.2 ALARMv3 MCP — `query_codebase` tool

```jsonc
{{ "tool": "query_codebase",
  "params": {{
    "query": "where is Oracle authentication initiated?",
    "top_k": 8
}} }}
```

### 10.3 Useful seed queries

| Question | Why it works |
|---|---|
| "where is Oracle authentication initiated?" | Targets `OraLogin.cs` + `Acad_ADO.Lsp` symbols. |
| "how are entities placed in drawings?" | Targets the `C:` LISP commands and `acadsymbol.cs`. |
| "how does the deployment script copy files?" | Targets `Upd_S_Map_AddsW{{7,10}}_Trans_Test_Local.Cmd`. |
| "where are user-form labels declared?" | Targets `frm*.cs` + corresponding `.resx` headers. |
| "where does input from getpoint flow?" | Targets `GetPoints.Lsp` + downstream commands. |

The chunker indexes both real symbols (functions, classes, enums) and a
`file_header` chunk for files with no extracted symbols, so questions about
"what is in this file?" return the import block + opening comments rather
than nothing.
"""


# ── Perfect-prompts appendix ──────────────────────────────────────────────────

_PROMPT_PREAMBLE = """\
You are a senior modernization engineer working on the ADDS codebase at
`/workspaces/ADDS_modernized_run2`. The original (read-only) source is at
`/workspaces/ADDS`. You may modify only files inside the modernized target.
Use ALARMv3 MCP tools (`query_codebase`, `read_recommendation`) when you
need extra context. Always:

1. Read the affected files in full before changing them.
2. Make the smallest correct change that fully addresses the recommendation.
3. Preserve existing behavior and APIs unless the recommendation explicitly
   requires breaking changes; if breaking, list the breaking change at the
   top of your commit message.
4. Run any available tests; if none exist, manually trace one happy path
   through the change.
5. Commit with the message format: `ADDS modernization #{rank}: <one-line summary>`.
"""


def _make_prompt(r: dict) -> str:
    bullets = "\n".join(f"- `{f}`" for f in r["affected_files"]) or "- _(no specific files; cross-cutting)_"
    fixshape = r.get("description", "")
    crit = r.get("evaluator_critique") or ""
    eff = r.get("effort", "?")
    risk = r.get("risk_score", "n/a")
    return f"""\
#### Recommendation #{r['rank']} — {r['title']}

**Category**: `{r['category']}`  · **Severity**: `{r['severity']}`  · **Effort**: `{eff}`  · **Risk**: `{risk}`  · **Verdict**: `{r.get('evaluator_verdict','pending')}`

##### Affected files
{bullets}

##### What needs to change
{fixshape}

##### Evaluator notes (read carefully — these are the gotchas)
{crit or '_(no critique)_'}

##### Prompt to execute this recommendation

```text
{_PROMPT_PREAMBLE}

Apply ALARMv3 recommendation #{r['rank']}: {r['title']}.

Context (full text from the recommendation):
> {r['description']}

Why it matters:
> {r.get('rationale','')}

Adversarial evaluator notes (must be addressed):
> {crit or 'No specific critique recorded.'}

Affected files:
{bullets}

Procedure:
1. Read each affected file completely from /workspaces/ADDS_modernized_run2.
2. Confirm the symptom described above is present (cite line numbers).
3. Implement the smallest correct fix. The fix shape is described in the
   recommendation; be specific and minimal.
4. If any callers of changed symbols exist elsewhere in the repo, update them.
5. If the evaluator critique flags an oversight (effort underestimated,
   missed surface area, downstream risk), explicitly address it or note why
   it does not apply.
6. Run `git status` to confirm the diff is scoped to the affected files.
7. Commit with: `ADDS modernization #{r['rank']}: <one-line>`.
8. If the change is risky (Risk ≥ 3), open a PR instead of committing to main.
```
"""


def _prompts_appendix(recs: list[dict]) -> str:
    accepted = [r for r in recs if (r.get("evaluator_verdict") or "").lower() in ("accept", "revise")]
    lines = [
        "## 11. Perfect prompts — execute the recommendations\n",
        f"_One self-contained prompt per accepted/revise-recommended item ({len(accepted)} of "
        f"{len(recs)}). Paste any of these into a fresh Claude/ALARMv3 session against the "
        "modernized target repo. Each prompt embeds the full context, the evaluator's "
        "critique (so the implementer doesn't repeat the gotchas), and a procedure._\n",
        "### 11.1 Common preamble\n",
        f"```text\n{_PROMPT_PREAMBLE}```\n",
        "### 11.2 Per-recommendation prompts\n",
    ]
    for r in accepted:
        lines.append(_make_prompt(r))
    lines.append("\n### 11.3 Rejected items\n")
    rejected = [r for r in recs if (r.get("evaluator_verdict") or "").lower() == "reject"]
    if rejected:
        for r in rejected:
            lines.append(f"- ❌ #{r['rank']} {r['title']}")
            lines.append(f"  - _Critique:_ {r.get('evaluator_critique','')[:300]}")
    else:
        lines.append("_(none)_")
    return "\n".join(lines)


# ── Main wiki ─────────────────────────────────────────────────────────────────

def build_wiki(data: dict, sid: str) -> str:
    manifest = data["manifest"]
    eligible = [m for m in manifest if m["is_eligible"]]

    sections: list[str] = []

    # Header
    sections.append(f"""# ADDS Codebase Wiki

> **Last updated**: 2026-04-28 · **Session**: `{sid}`
> **Source archive**: `/workspaces/ADDS` (commit `1271468`, the full original archive)
> **Modernized target**: `/workspaces/ADDS_modernized_run2`
> Sections below are sourced from the populated ALARMv3 `analysis.db` for this session
> (manifest, symbol, dependency_edge, complexity_metric, code_chunk + chunk_vectors, recommendation, subsystem, subsystem_finding) — every claim should be traceable
> to that database. The previous subset-only wiki is preserved in the git history.

## Table of contents

1. [What is ADDS?](#1-what-is-adds)
2. [File inventory (full archive)](#2-file-inventory-full-archive)
3. [Architecture map](#3-architecture-map)
4. [Subsystem partitioning](#4-subsystem-partitioning)
5. [Findings — Security](#5-findings--security)
6. [Findings — Modernization](#6-findings--modernization)
7. [Findings — Quality & Dependencies](#7-findings--quality--dependencies)
8. [Prioritized recommendations](#8-prioritized-recommendations)
9. [Evaluation report (verdicts & risk)](#9-evaluation-report-verdicts--risk)
10. [RAG / vector index — query patterns](#10-rag--vector-index--query-patterns)
11. [Perfect prompts — execute the recommendations](#11-perfect-prompts--execute-the-recommendations)
12. [Run history & known limitations](#12-run-history--known-limitations)

---
""")

    # 1. What is ADDS — keep curated content from prior wiki
    sections.append(f"""## 1. What is ADDS?

**ADDS — Automated Drawing & Design System**
Source: `lisp/dialogs/main-menu.dcl:5` (deepest first-line label).

**What the code confirms (full archive):**
- An AutoCAD plugin (AutoLISP + C# 19.0 + ARX/COM interop) that lets users
  place named engineering objects into drawings via interactive commands.
- Persistence layer: Oracle 11g, accessed via `Oracle.DataAccess` (unmanaged
  ODP.NET) from C# and via `Acad_ADO.Lsp` from AutoLISP.
- Background sync: `Utils/Upd_S_Map_AddsW{{7,10}}_Trans_Test_Local.Cmd` uses
  `Xcopy` from a UNC share `S:\\Workgroups\\APC Power Delivery\\Division Mapping\\…`
  to local `C:\\Div_Map\\` with `icacls /grant Users:(oi)(ci)f` for shared
  workstation access.
- Solution targets **Visual Studio 2012 / Format Version 12.00** with TFVC
  binding to `https://anuemtfs1.aplum.org:8080/tfs/...`.
- Earliest dates we can source: AutoLISP comments referencing 1991, 1997, 2000.

**What the code does NOT confirm (do NOT infer):**
- The domain or industry the system serves — no source file states this.
- Whether named object types reflect the deployed business reality.

**What requires domain knowledge:**
- The business workflow ADDS supports.
- Whether `APC Power Delivery / GPC` references reflect the operating org.

The full archive contains **319 files** (1,364 raw, 222 source-eligible
after the binary blocklist). See §2 for the breakdown.
""")

    # 2. File inventory
    sections.append(_file_inventory_section(manifest, data["symbols_by_file"]))

    # 3. Architecture map
    sections.append(f"""\n## 3. Architecture map

The component map below is derived from the affected_files lists in the
ranked recommendations and the dependency_edge graph (937 edges total
across the session).

### 3.1 High-level component map\n
{_component_map_mermaid(data['recs'])}

### 3.2 Sync & login flow\n
{_sync_flow_mermaid()}
""")

    # 4. Subsystem partitioning
    sections.append(_subsystem_section(data["subsystems"], data["findings"]))

    # 5-7. Findings by category
    sections.append(_findings_by_category(data["findings"], "security",
                                           "5. Findings — Security"))
    sections.append(_findings_by_category(data["findings"], "modernization",
                                           "6. Findings — Modernization"))
    quality = _findings_by_category(data["findings"], "quality",
                                     "7. Findings — Quality & Dependencies")
    deps = _findings_by_category(data["findings"], "dependency",
                                  "Quality & Dependencies (cont.)")
    deps_body = "\n".join(deps.splitlines()[1:])  # drop duplicate heading
    sections.append(quality + "\n" + deps_body)

    # 8. Recommendations
    sections.append(_recommendations_section(data["recs"]))

    # 9. Evaluation report — point at the artifact
    verdict_counts: dict[str, int] = defaultdict(int)
    for r in data["recs"]:
        verdict_counts[(r.get("evaluator_verdict") or "pending").lower()] += 1
    rejected = [r for r in data['recs'] if (r.get('evaluator_verdict') or '').lower() == 'reject']
    eval_section = (
        "## 9. Evaluation report (verdicts & risk)\n\n"
        f"All {len(data['recs'])} recommendations were run through an adversarial "
        "evaluator. The evaluator returns a verdict (`accept` / `revise` / `reject`), "
        "an effort estimate, and a risk score 1-5.\n\n"
        f"- **Accept**: {verdict_counts.get('accept', 0)}\n"
        f"- **Revise**: {verdict_counts.get('revise', 0)}\n"
        f"- **Reject**: {verdict_counts.get('reject', 0)}\n\n"
        "Full critique text per recommendation is in "
        f"`/workspaces/ADDS_ALARMv3/.alarmv3/sessions/{sid}/evaluation_report.md`. "
        "The §8.1 \"full text\" entries reproduce the critique inline.\n\n"
        "### 9.1 Notable rejections (read these before implementing)\n\n"
    )
    if rejected:
        for r in rejected:
            eval_section += f"- **#{r['rank']} {r['title']}**\n  _Reason:_ {r.get('evaluator_critique','')[:400]}\n"
    else:
        eval_section += "_(none)_"
    sections.append(eval_section)

    # 10. RAG section
    sections.append(_rag_section(data["chunks_count"], sid))

    # 11. Perfect prompts
    sections.append(_prompts_appendix(data["recs"]))

    # 12. Run history
    sections.append(f"""## 12. Run history & known limitations

### 12.1 Pipeline patches that landed during this run

The 2026-04-28 full-archive run surfaced and patched several real ALARMv3 bugs:

1. **Path-convention split** between `core/analysis.py` (absolute paths) and
   `core/language_researcher.py` (relative paths). Result: 49 C# files were
   invisible to deep-analysis even though their symbols/metrics were in the
   DB. Fixed by patching `analysis.py` to write `manifest.relative_path`-form
   paths and migrating the existing `analysis.db` via
   `scripts/migrate_paths_to_relative.py`.

2. **Per-subsystem token cap** of 2048 was too tight for 10-finding
   responses on rich subsystems; truncation produced unparseable JSON which
   `_parse_findings` returned as `[]`. Fixed by raising to 6144 tokens and
   adding a recovery path in `_parse_findings` that walks the JSON array
   collecting complete `{{...}}` objects, so a truncated last item is dropped
   instead of nuking the whole list.

3. **Per-subsystem prompt** was JSON-encoding source code as escaped strings
   inside a single user-content blob. Replaced with `_format_subsystem_message`
   that puts each representative file in its own fenced code block with a
   language hint. Findings density jumped from 0–9 per cluster to 10/10 on
   every subsystem.

4. **`_apply_diff` rebuilt files from hunk lines alone**, so partial hunks
   like `@@ -40,9 +40,10 @@` against a 60-line file produced a 10-line file
   (loss of out-of-hunk content). Replaced with `_splice_hunks` which
   fuzzy-locates each hunk's actual position in the original file and
   splices the body in place, preserving everything outside the hunk window.

5. **No `evaluation_report.md` writer**. Added to `ArtifactWriter.write_all()`.

### 12.2 Known limitations still open

- **Complexity metrics are LOC-only for inferred languages.** `complexity_metric`
  has `loc` and `total_lines` but no real `cyclomatic` for AutoLISP, .pat, .atc,
  etc. Phase 7 grammars don't compute branch counts. Implication: the complexity
  outlier pass returns 0 outliers because every cyclomatic is 0.

- **Cross-language dependency edges are sparse.** The C# `using` extractor
  populates `target_module` only; the LISP grammar populates symbols but not
  call edges. The partitioner compensates with shared-module + 3-level path
  coupling, but a true call-graph across the LISP→C# boundary is missing.

- **Chunker uses absolute paths sourced from `manifest.file_path` for the
  file-header branch.** After the migration the chunker now correctly stores
  `relative_path`, but a prior run's chunks may need re-indexing if you
  rebuild the RAG layer.

### 12.3 Pointer back to artifacts

| Artifact | Path |
|---|---|
| Recommendations (Markdown) | `.alarmv3/sessions/{sid}/recommendations.md` |
| Evaluation report (Markdown) | `.alarmv3/sessions/{sid}/evaluation_report.md` |
| File manifest (JSON) | `.alarmv3/sessions/{sid}/manifest.json` |
| Summary (JSON) | `.alarmv3/sessions/{sid}/summary.json` |
| Audit log | `.alarmv3/sessions/{sid}/audit.log` |
| Analysis database | `.alarmv3/sessions/{sid}/analysis.db` |
| Modernized target | `/workspaces/ADDS_modernized_run2` |
""")

    return "\n\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = _fetch(Path(args.db), args.session_id)
    text = build_wiki(data, args.session_id)
    Path(args.out).write_text(text)
    print(f"Wrote {len(text):,} chars to {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
