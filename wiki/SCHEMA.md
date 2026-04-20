# ALARMv3 LLM Wiki — Schema & Conventions

Inspired by [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## What this wiki is

A persistent, compounding knowledge base maintained by an LLM. Not a copy of planning docs — a **synthesis** layer. Every source ingested, every insight discovered, every decision made gets filed here so future conversations start informed rather than blank.

Division of labor:
- **Humans** curate sources, ask questions, make decisions.
- **LLM** summarizes, files, cross-references, audits.

## Directory structure

```
wiki/
├── SCHEMA.md         — this file; conventions and operations
├── index.md          — content catalog, one line per page
├── log.md            — append-only chronological ingest/query log
├── project/          — ALARMv3-specific decisions and status
├── concepts/         — general AI/engineering concepts relevant here
├── personas/         — synthesized views of AI practitioners
├── architecture/     — design patterns and structural decisions
└── tools/            — specific tools, SDKs, frameworks
```

## Page format

Each page uses this header:

```markdown
# Title
> **Status**: current | stale | draft
> **Last updated**: YYYY-MM-DD
> **Tags**: tag1, tag2

One-sentence summary used in index.md.
```

Then free-form content. Use `## See also` at the bottom for cross-links.

## Operations

### Ingest
Drop a source (doc, URL, transcript, conversation). The LLM:
1. Reads and extracts key takeaways.
2. Updates relevant existing pages.
3. Creates new pages if the concept is new.
4. Appends an entry to `log.md`.
5. Updates `index.md`.

### Query
Ask a question. The LLM:
1. Searches relevant pages.
2. Synthesizes an answer with page citations.
3. Files any new discovery back as a page update or new page.
4. Appends a query entry to `log.md`.

### Lint
Periodic audit. The LLM checks for:
- Contradictions between pages.
- Stale claims (status should flip to `stale`).
- Orphan pages (no cross-links).
- Missing cross-references.
- Gaps relative to known project scope.

## Log entry format

```
## [YYYY-MM-DD] <op> | <title>
<one-line summary of what changed or was discovered>
Pages touched: page1.md, page2.md
```

## Index entry format

One line per page: `- [Title](path/to/page.md) — one-sentence hook`
