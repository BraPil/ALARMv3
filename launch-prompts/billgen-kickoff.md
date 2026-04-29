# BillGen kickoff prompt — paste into a fresh Claude Code session

> **What this is**: a single self-contained prompt to paste at the start of the BillGen modernization session. Do not edit before pasting; just paste verbatim. Adjust target stack details (.NET version / database version / host application version) inline once you know them.
>
> **Last updated**: 2026-04-29 · **Source playbook**: [`wiki/runbooks/billgen-live-demo.md`](../wiki/runbooks/billgen-live-demo.md)
>
> **Prerequisites that must be true before pasting**:
> - `/workspaces/BillGen/` exists (read-only source clone) — clone from `BraPil/BillGen_Orig` or wherever the archive lives
> - `BraPil/BillGen_modernized_run1` GitHub repo exists (private)
> - `/workspaces/BillGen_modernized_run1/` is a fresh local clone of the archive with origin pointed at the new repo
> - `/workspaces/BillGen_ALARMv3/` exists (or will be created by the run)
> - `ANTHROPIC_API_KEY` is set; Ollama is running with `nomic-embed-text`

---

## The prompt

```
You're picking up the BillGen modernization run, end-to-end. This is the
second application of the validated ADDS template (committed across
BraPil/ALARMv3, BraPil/ADDS_modernized_run2, and BraPil/ADDS_ALARMv3 on
2026-04-29).

REQUIRED READING — read these in order before doing anything else:

1. BraPil/ALARMv3 wiki/runbooks/billgen-live-demo.md
   — the day-by-day playbook for this exact run

2. BraPil/ALARMv3 wiki/runbooks/full-archive-run.md
   — the upstream pipeline runbook the playbook depends on

3. BraPil/ALARMv3 wiki/project/adds-modernization-plan.md
   — the validated plan template; BillGen's plan mirrors this structure

4. BraPil/ADDS_modernized_run2 Documentation/README.md
   — folder structure to mirror for BillGen

5. BraPil/ADDS_modernized_run2 Documentation/deferred-validation.md
   — the hand-off-checklist template

After reading: tell me what you understand and confirm:
  * the three workspaces (source / modernized target / analysis workspace)
  * the 5 phases in order with their forced-minimum scope
  * the forced-vs-optional discipline that prevents this from becoming a
    rewrite
  * what you cannot validate from this Codespace (deferred-validation.md
    is the SSoT)

THEN run the BillGen Day 0 pre-flight (billgen-live-demo.md §0):
  * verify the three workspaces exist with the right remotes
  * verify engine settings (full-archive-run.md §1.5)
  * surface the Phase 0 open questions (target framework, internal libs,
    auth mode, backwards-compat, OS matrix, deployment scope, source-
    control history migration)

Pause for my answers on the Phase 0 questions before proceeding to Day 1.

DAY 1 (after Phase 0 answers):
  * Run scripts/demo_full_run.py against /workspaces/BillGen
  * Run all post-run sanity checks (full-archive-run.md §3)
  * Read the .csproj/.sln/app.config artifacts directly first
  * Run the 12 RAG discovery queries with --rerank (billgen-live-demo.md
    §1.4) — adjust vocabulary for BillGen's domain
  * Pull the recommendation table from the deep-analysis run

DAY 2: write the BillGen modernization plan at
  BraPil/ALARMv3 wiki/project/billgen-modernization-plan.md
following the 4-section structure (current state | target | forced-vs-
optional | phased plan with risk register and open questions). Commit
and push.

DAYS 3-7: execute Phases 1-5 at code level in
  BraPil/BillGen_modernized_run1/Updated Files/
documenting each phase under
  BraPil/BillGen_modernized_run1/Documentation/

The ADDS Updated Files/ tree is the structural template. Mirror it
exactly:
  Updated Files/
    src/<project>/
    tests/<project>.Tests/
    Deploy/
    config/
    .github/workflows/

After every phase: commit with a substantive message describing what
changed and why, push, and proceed to the next phase. Do NOT stack
multiple phases into one commit — the per-phase boundary is what makes
the work reviewable.

End the run by:
  * writing Documentation/deferred-validation.md (the on-host TODO list)
  * updating BraPil/ALARMv3 wiki/log.md with a new entry summarizing
    the run
  * updating BraPil/ALARMv3 wiki/index.md page count
  * updating BraPil/BillGen_ALARMv3 with the analysis state, RUN_PLAN,
    and wiki summary
  * committing and pushing all three repos

CRITICAL CONSTRAINTS:

* Honest scope statement. A Linux Codespace cannot validate plugin-host
  behavior, database round-trips, or PowerShell installers on Windows.
  Every phase doc must clearly distinguish "code-level applied" from
  "acceptance-tested on the production host" — the latter goes in
  deferred-validation.md.

* GITHUB_TOKEN gotcha. Pushes to BillGen repos other than the primary
  Codespace repo need:
    env -u GITHUB_TOKEN -u GH_TOKEN git push origin main
  Otherwise the Codespace's scoped ghu_* token blocks the push.

* ADDS_Orig is a read-only archive — never push to it. The same applies
  to BillGen_Orig if a separate archive repo exists. Use
  `git remote set-url --push origin DISABLE_PUSH_TO_READ_ONLY_ARCHIVE`
  on any source archive remote.

* Do NOT ship a generic unc_path regex in the secret-chunker. The ADDS
  draft generated 800 false positives from LISP-escaped local paths.
  If BillGen has literal UNC strings, use a string-literal-boundary
  lookbehind: (?<=["'\s])\\{2,4}[a-zA-Z][\w-]+\\{1,2}[\w.$-]+

* When building reranker prompts, use f-strings NOT str.format() —
  chunk content contains literal {} from C# array initializers, JSON,
  dict literals.

* Do NOT delete the LegacyDecrypt shim from the encryption migration
  until you've confirmed no callers persist encrypted blobs across
  builds. The flag MigrationConfig.TryLegacyDecryptOnFailure controls
  this.

When you've finished reading, give me a one-paragraph summary of your
understanding plus the Phase 0 open questions you need answers on
before Day 1. We'll go from there.
```

---

## Why this prompt is shaped the way it is

- **Required-reading list first** — the Claude session starts cold; we cannot rely on it remembering anything from this conversation. The reading list pulls in the playbook, upstream runbook, validated plan template, and folder-structure example. After that, the session has the same context we did.
- **Explicit pause for Phase 0 answers** — the open questions block is the part that requires *human* input, not Claude's. The prompt forces a checkpoint there so the session doesn't burn cycles guessing on `ScCool*` equivalents or auth modes.
- **Day-by-day structure** — 7 days isn't a deadline, it's a structure. Each day has a single deliverable so progress is reviewable. Better than "do the modernization."
- **Critical constraints listed inline** — the gotchas that already cost us time on ADDS (GITHUB_TOKEN, unc_path regex, str.format, LegacyDecrypt) are reminded in the prompt itself so the session doesn't re-learn them.
- **End-of-prompt summary request** — calibration check before any work happens. If the summary is wrong, we redirect before paying for cycles.

## What to update before pasting

- **Repo names**: assumes `BraPil/BillGen_Orig`, `BraPil/BillGen_modernized_run1`, `BraPil/BillGen_ALARMv3`. Adjust if BillGen lives elsewhere.
- **Workspace paths**: assumes `/workspaces/BillGen`, `/workspaces/BillGen_modernized_run1`, `/workspaces/BillGen_ALARMv3`.
- **Target stack details**: framework version, database version, host application version. Add inline once known. The prompt is generic enough that this isn't strictly necessary up front, but specifying earlier saves Day 1 time.

## Variant: if you want a shorter, more autonomous prompt

```
You're running the BillGen modernization end-to-end per
BraPil/ALARMv3 wiki/runbooks/billgen-live-demo.md (the validated ADDS
template applied to a new codebase). Read that file plus
wiki/project/adds-modernization-plan.md as your template, then
proceed. Pause only at the Phase 0 question block to surface the
unknowns I need to answer. After Phase 0, run autonomously through
Days 1-7, committing after each phase. End with deferred-validation.md
and wiki updates per the runbook.
```

Use this if you trust the session to make Phase 0 surface-then-pause work without explicit guidance. The longer prompt above is safer for the first BillGen run; the short one is good for runs 2+.
