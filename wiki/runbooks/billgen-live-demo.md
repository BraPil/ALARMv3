# BillGen live-demo runbook

> **Status**: ready · **Created**: 2026-04-29 · **Tags**: live-demo, modernization, billgen, end-to-end
>
> Synthesis of every lesson learned from the ADDS run (2026-04-28 → 2026-04-29). This is the executable playbook for the next codebase. Sized for a working week (5-7 days, ~30-40 hours of focused engineer time).
>
> **Pair this with**: [`full-archive-run.md`](full-archive-run.md) for the upstream pipeline runbook and [`../project/adds-modernization-plan.md`](../project/adds-modernization-plan.md) for the planning template.

## What this is

ALARMv3's analysis pipeline (full-archive-run.md) ends at a recommendation list and a populated `analysis.db`. This runbook covers what happens **after** that: turning the analysis into a forced-minimum modernization plan and executing it at code level. The ADDS run from 2026-04-29 validated the entire flow end-to-end and produced:

- A 4-section plan ([`adds-modernization-plan.md`](../project/adds-modernization-plan.md))
- A `Updated Files/` tree containing the migrated codebase
- A `Documentation/` folder with phase-by-phase records
- A `deferred-validation.md` enumerating everything that requires the production host (Windows + AutoCAD 2025 + Oracle 19c, in ADDS's case) to acceptance-test

The same shape applies to BillGen, with target-stack details adjusted for whatever runtime/database BillGen sits on.

---

## Day 0 — Pre-flight (~1 hour)

Do these BEFORE starting the run, not during.

### 0.1 Three workspaces

Per the [definitions table in the upstream runbook](full-archive-run.md#0-definitions):

- [ ] **Source archive**: `/workspaces/BillGen/` — read-only clone of `BraPil/BillGen_Orig`. Treat like a git tag pinned to a commit. Set `git remote set-url --push origin DISABLE_PUSH_TO_READ_ONLY_ARCHIVE`.
- [ ] **Modernized target**: `/workspaces/BillGen_modernized_run<N>/` — fresh clone of the source archive. New GitHub repo `BraPil/BillGen_modernized_run<N>` (private). Origin points at the new repo, NOT the source archive.
- [ ] **Analysis workspace**: `/workspaces/BillGen_ALARMv3/` — holds `.alarmv3/sessions/<id>/`, `RUN_PLAN.md`, `wiki/`. Initially empty (or a fresh `.alarmv3/` dir).

### 0.2 Engine settings to verify (~30s)

Quick grep for the load-bearing knobs before kicking off — see [section 1.5 of the upstream runbook](full-archive-run.md#15-critical-engine-settings-to-verify-before-running). The full table is there; the most likely-to-regress items:

- `core/knowledge.py` `_OVERVIEW_LINES = 200` ✓
- `core/knowledge.py` `_extract_secret_chunks` called from `_create_chunks` ✓
- `core/knowledge.py` `_SECRET_PATTERNS` does NOT contain a generic `unc_path` regex ✓
- `scripts/rag_query.py` FTS5 indexes `chunk_type + symbol_name + content` ✓
- `scripts/rag_query.py` `retrieve()` runs vec + kw + path + secret sources

### 0.3 Phase 0 unblocking decisions

These won't block discovery but they WILL block the eventual on-workstation acceptance test. Surface them on Day 0 so they're being chased in parallel:

- [ ] Target framework: what version of the runtime, database, and host application is the migration aiming for?
- [ ] Internal dependencies: do .NET 8 (or equivalent) builds exist for any internal corporate libraries the codebase pulls from a private feed?
- [ ] Authentication mode: integrated security / Kerberos vs. username + password — affects how the connection string and DPAPI / Key Vault paths are wired.
- [ ] Backwards compatibility: does the new build need to read persisted blobs (encrypted credentials, config files) produced by the legacy build? Drives whether a one-release migration shim is needed.
- [ ] OS support matrix.
- [ ] TFS / source-control history migration.
- [ ] Deployment scope (single dev install vs. N hundred user workstations) — drives PS1 vs. WiX MSI choice.

The full open-questions block from the [ADDS plan](../project/adds-modernization-plan.md#9-open-questions-that-need-decisions-before-kickoff) is a good template.

---

## Day 1 — Discovery (~4-6 hours)

### 1.1 Run the full-archive pipeline

Per [section 2 of the upstream runbook](full-archive-run.md#2-running-the-pipeline):

```bash
cd /workspaces/ALARMv3
.venv/bin/python scripts/demo_full_run.py \
  --source /workspaces/BillGen \
  --workspace /workspaces/BillGen_ALARMv3 \
  --target /workspaces/BillGen_modernized_run1
```

Watch for the state transitions and the `AUTOPILOT_ACCEPT` lines.

### 1.2 Run all post-run sanity checks

Per [section 3](full-archive-run.md#3-post-run-sanity-checks). Stop here and triage if any of these fail:

- Eligible file count > 100 (> 100 for any non-toy codebase)
- No language has 1000+ files unless expected (catches binary blocklist regressions)
- `SELECT COUNT(*) FROM symbol WHERE file_path LIKE '/%'` returns 0 (path-convention check)
- Every subsystem returns non-zero `findings_count`
- Implementation actually committed: `commit_hash IS NOT NULL` for accepted plan items

### 1.3 Read project artifacts directly (faster than RAG)

Before driving the RAG, read the project files directly — they're tiny:

```bash
cat /workspaces/BillGen/path/to/*.sln
find /workspaces/BillGen -name '*.csproj' -exec cat {} \;
find /workspaces/BillGen -name 'app.config' -o -name 'web.config' -o -name 'packages.config' -exec cat {} \;
find /workspaces/BillGen -name 'appsettings*.json' -exec cat {} \;
```

Capture in your Day 1 working notes:
- Target framework version (`<TargetFrameworkVersion>v4.7</TargetFrameworkVersion>` etc.)
- Solution format / Visual Studio version
- Source-control bindings (TFS? SVN? Git?)
- NuGet state — `<PackageReference>` modern, `<HintPath>` legacy, neither (raw refs)
- Reference paths that name external products (AutoCAD, Oracle, third-party SDKs)
- Output path and platform target

### 1.4 RAG discovery queries (8-12 with `--rerank`)

```bash
DB=/workspaces/BillGen_ALARMv3/.alarmv3/sessions/<id>/analysis.db

# Adjust each query's vocabulary for BillGen's domain. The shape stays the same.
python3 scripts/rag_query.py --db "$DB" --top-k 6 --rerank \
  --query "How does the database connection get established, what driver is used, and how are queries constructed and executed?"
python3 scripts/rag_query.py --db "$DB" --top-k 6 --rerank \
  --query "What plugin/host APIs and P/Invoke calls does the codebase use? Look for managed namespace imports and unmanaged DLL references."
python3 scripts/rag_query.py --db "$DB" --top-k 8 --rerank \
  --query "How do the C# and any embedded scripting layer (LISP/Python/JS/etc.) interoperate? How are routines loaded and how do they call into each other?"
python3 scripts/rag_query.py --db "$DB" --top-k 6 --rerank \
  --query "What WinForms / WPF / web UI controls and patterns are used? Look at form lifecycle, data binding, and any third-party UI libraries."
python3 scripts/rag_query.py --db "$DB" --top-k 6 --rerank \
  --query "How does user authentication work end-to-end? From the login form through credential validation, and how are authenticated credentials stored and used for subsequent requests?"
python3 scripts/rag_query.py --db "$DB" --top-k 5 --rerank \
  --query "What threading patterns does the code use? Any Thread, Task, async/await, BackgroundWorker, or Invoke/BeginInvoke usage?"
python3 scripts/rag_query.py --db "$DB" --top-k 5 --rerank \
  --query "How is configuration loaded? Where do INI files, XML lookup files, and registry settings get read? Where do hardcoded paths come from?"
python3 scripts/rag_query.py --db "$DB" --top-k 6 --rerank \
  --query "How is the product deployed and installed on user workstations? What's the install chain?"
python3 scripts/rag_query.py --db "$DB" --top-k 5 --rerank \
  --query "What is the application entry point? Where is the main initialization implemented and what gets registered?"
python3 scripts/rag_query.py --db "$DB" --top-k 5 --rerank \
  --query "How big is the secondary-language codebase (LISP/scripts/etc.) and what does it do that the C# code doesn't?"
python3 scripts/rag_query.py --db "$DB" --top-k 5 --rerank \
  --query "What unit tests, integration tests, or test infrastructure exists? Any xUnit, NUnit, MSTest, or test fixtures?"
python3 scripts/rag_query.py --db "$DB" --top-k 6 --rerank \
  --query "Where are hardcoded credentials, passwords, encryption keys, or database connection strings?"
```

The auto-fired path/secret sources will activate when these queries hit security/file-type vocabulary. Trace tags in `--raw` mode (`[kw+secret+vec]` etc.) tell you which source promoted each chunk — useful for debugging.

### 1.5 Pull existing recommendations

```bash
python3 -c "
import sys, sqlite3, pysqlite3
sys.path.insert(0, '/workspaces/ALARMv3/src')
from alarmv3.core.knowledge import _vec_conn
from pathlib import Path
db = Path('/workspaces/BillGen_ALARMv3/.alarmv3/sessions/<id>/analysis.db')
conn = _vec_conn(db)
for r in conn.execute('SELECT id, title, severity, effort, rationale FROM recommendation ORDER BY rank LIMIT 25').fetchall():
    print(f'[{r[\"severity\"]:>5} | effort={r[\"effort\"]:>6}] {r[\"title\"]}')"
```

This is the deep-analysis adversarial output. Use as a sanity-check on the plan's scope, not as the plan itself.

---

## Day 2 — Plan (~3-5 hours)

Write the modernization plan as `BraPil/ALARMv3/wiki/project/billgen-modernization-plan.md` using the [ADDS plan as template](../project/adds-modernization-plan.md).

### 2.1 Four-section structure (mandatory)

1. **Executive summary** — what the migration is, why now, what's NOT a rewrite
2. **Current state baseline table** — RAG-cited; covers solution artifacts, framework, runtime bindings, plugin/host integration, secondary language scope, auth, UI, threading, config, deployment, tests
3. **Target state table** — same row structure as current; column shows what changes
4. **Forced vs optional changes** — the central strategic insight; two-column table separating what cannot ship without vs. what's opportunistic

### 2.2 Phased plan

5 phases is the validated count from ADDS. Each phase has:
- Tasks (ordered)
- Risks
- Acceptance criteria
- Estimated duration

### 2.3 Backlog and risk register

Ranked opportunity backlog (post-shipping items, ~10-15 entries with effort estimates).

Risk register with probability × impact × mitigation per row.

Open-questions block surfacing the Phase 0 decisions.

### 2.4 Save plan to ALARMv3 wiki

```bash
cd /workspaces/ALARMv3
git add wiki/project/billgen-modernization-plan.md
git commit -m "Wiki: BillGen modernization plan"
env -u GITHUB_TOKEN -u GH_TOKEN git push origin main
```

---

## Day 3 — Phase 1: framework retarget (~3-5 hours)

### 3.1 Set up Updated Files/ structure

```bash
cd /workspaces/BillGen_modernized_run1
mkdir -p "Updated Files/src" "Updated Files/tests" "Updated Files/Deploy" "Updated Files/config" "Updated Files/.github/workflows" Documentation
```

### 3.2 Bulk-copy unchanged files

```bash
cp -r '<source-tree>/.' 'Updated Files/src/<project-name>/'
# Strip TFVC / VSTS bindings
rm -f 'Updated Files/src/<project-name>/*.vspscc'
# Drop legacy deploy scripts (replaced by PowerShell in Phase 3)
find 'Updated Files' \( -iname '*.vbs' -o -iname '*.cmd' -o -iname '*.bat' \) -delete
```

### 3.3 Write SDK-style csproj

Template at [`/workspaces/ADDS_modernized_run2/Updated Files/src/Adds/Adds.csproj`](https://github.com/BraPil/ADDS_modernized_run2/blob/main/Updated%20Files/src/Adds/Adds.csproj). Adjust target framework, package references, and host-application reference paths for BillGen's stack.

### 3.4 Mechanical transforms

```bash
# Drop framework attributes that became no-ops
sed -i '/^\s*\[SuppressUnmanagedCodeSecurity\]\s*$/d' src/<project>/*.cs
sed -i '/^using System\.Security;$/d' src/<project>/*.cs

# Swap legacy DB driver namespace (example for ODP.NET classic → managed)
find . -name '*.cs' -exec sed -i 's/Oracle\.DataAccess\.Client/Oracle.ManagedDataAccess.Client/g' {} \;

# Update version-pinned API references (e.g. acdb17.dll → acdb25.dll for AutoCAD)
# Document any TODO(phase-0) markers for runtime-verification of mangled names
```

### 3.5 Write `Documentation/phase-1-*.md`

Document every sed pass, every TODO marker, and every file changed. ADDS template at [`/workspaces/ADDS_modernized_run2/Documentation/phase-1-net8-retarget.md`](https://github.com/BraPil/ADDS_modernized_run2/blob/main/Documentation/phase-1-net8-retarget.md).

---

## Day 4 — Phase 2: security minimums (~3-5 hours)

### 4.1 Replace shared-secret crypto with platform secret API

If the codebase has hardcoded encryption keys / salts: replace with DPAPI (Windows) or Key Vault. Preserve a `LegacyDecrypt` shim marked `[Obsolete]` for one-release blob migration. ADDS template: [`utilities.cs Encrypt/Decrypt`](https://github.com/BraPil/ADDS_modernized_run2/blob/main/Updated%20Files/src/Adds/utilities.cs).

### 4.2 Parameterize SQL on priority sites

Use the RAG to find every `sbSQL.Append("' + var + '")` site:

```bash
python3 scripts/rag_query.py --db "$DB" --top-k 12 --rerank \
  --query "Where is user input concatenated into SQL queries (SQL injection risk)?"
```

For each site:
- Switch to bind parameters (`:name` for Oracle, `@name` for SQL Server)
- Add a parameter dictionary to the helper signature if needed (ADDS used `Utilities.GetResults(StringBuilder, string, IDictionary<string,object>?)`)

### 4.3 Wrap every disposable in `using`

`Connection`, `Command`, `DataReader`, `DataAdapter`, `DataSet`, file streams. ADDS bundle: commit `2ad9ee9` started this; continue per-file.

### 4.4 Connection-string concatenation → builder API

Replace string-concat with `OracleConnectionStringBuilder` / `SqlConnectionStringBuilder` so values containing `;` or `"` can't break out of fields.

### 4.5 Externalize connection string template

Move to `appsettings.json`. Secrets via DPAPI or Key Vault — never in source.

### 4.6 Document

`Documentation/phase-2-security.md`.

---

## Day 5 — Phase 3: PowerShell deployment (~3-5 hours)

### 5.1 Replace any VBS / Cmd / batch deploy chain

ADDS template:
- [`Install-Adds.ps1`](https://github.com/BraPil/ADDS_modernized_run2/blob/main/Updated%20Files/Deploy/Install-Adds.ps1)
- [`Uninstall-Adds.ps1`](https://github.com/BraPil/ADDS_modernized_run2/blob/main/Updated%20Files/Deploy/Uninstall-Adds.ps1)
- [`divisions.json`](https://github.com/BraPil/ADDS_modernized_run2/blob/main/Updated%20Files/Deploy/divisions.json)

Key choices:
- `[CmdletBinding(SupportsShouldProcess)]` — let users `-WhatIf` before running
- Detect target host (e.g. AutoCAD) install via registry, not hardcoded path
- `robocopy /MIR /XO /R:3` instead of `Xcopy /D /F /S` (mirror, only-newer, retry)
- Per-user ACL on writable cache directories (`Set-Acl` adds `$env:USERDOMAIN\$env:USERNAME` only — NOT Users group)
- All paths come from a `divisions.json` (or equivalent) — no hardcoded UNC / server names
- Idempotent: safe to re-run for upgrades

### 5.2 Authenticode-signing

Plan to sign with a corporate code-signing cert before pushing to user workstations. `ExecutionPolicy AllSigned` per-machine + cert installed on workstation = unblocks default-policy execution.

### 5.3 Document

`Documentation/phase-3-deployment.md`.

---

## Day 6 — Phase 4: configuration externalization (~3-5 hours)

### 6.1 Add typed config class

ADDS template: [`Common/AddsConfig.cs`](https://github.com/BraPil/ADDS_modernized_run2/blob/main/Updated%20Files/src/Adds/Common/AddsConfig.cs). Wraps `Microsoft.Extensions.Configuration.Json` with strongly-typed records. Loads from `Adds.dll` directory → deployed config dir → environment variables.

### 6.2 `appsettings.template.json`

Sections (adjust per BillGen):
- `Logging`
- `<RuntimeName>` (Oracle / SqlServer / etc.)
- `Paths` — every hardcoded UNC and local path
- `<TenantOrDivision>` — replaced at deploy time
- `FeatureFlags`
- `Migration` — one-release shims toggleable

### 6.3 Switch statements → dictionary lookups

Any `switch (orgName) { case "..." }` becomes a `Dictionary<string, T>`. Adding a new tenant/division/division becomes a config + dictionary entry, not a code change.

### 6.4 Document

`Documentation/phase-4-config.md`.

---

## Day 7 — Phase 5: tests + CI (~2-4 hours)

### 7.1 xUnit project

ADDS template at [`Adds.Tests/`](https://github.com/BraPil/ADDS_modernized_run2/tree/main/Updated%20Files/tests/Adds.Tests).

Initial test coverage focuses on the highest-leverage logic that doesn't require the production host:
- Config load (defaults + JSON load)
- Encryption migration (round-trip + non-determinism)
- Tenant / division lookup (pinned table)

Host-bound tests (anything that needs the AutoCAD / web app / etc. context) are scripted-launch tests — out of scope for the floor.

### 7.2 GitHub Actions

ADDS template at [`.github/workflows/ci.yml`](https://github.com/BraPil/ADDS_modernized_run2/blob/main/Updated%20Files/.github/workflows/ci.yml).

Two jobs:
- `build-and-test` (runs on `windows-latest` if Windows-bound; `ubuntu-latest` otherwise) — restore, build, test, format check
- `powershell-syntax` — PSScriptAnalyzer against `Deploy/*.ps1`

### 7.3 Document

`Documentation/phase-5-tests-and-ci.md`.

---

## Hand-off — `deferred-validation.md`

This is the single most important page produced by the run. Enumerate EVERY item that requires the production host to verify:

- `dotnet build` against host-application-managed assemblies
- Database connectivity round-trip
- Mangled-name capture (if any P/Invoke entries depend on host version)
- Host plugin loading (NETLOAD, IIS, etc.)
- PowerShell installer end-to-end on a clean target VM
- Internal corporate library availability on the new framework
- SQL injection long-tail audit
- LISP / scripted-language compatibility on new host
- End-to-end smoke test with a real production input

ADDS template at [`Documentation/deferred-validation.md`](https://github.com/BraPil/ADDS_modernized_run2/blob/main/Documentation/deferred-validation.md).

**Do not declare the migration shipped until every box in this file is checked.**

---

## Lessons learned from ADDS (validated 2026-04-29)

### Don't pretend to validate what you can't

A Linux Codespace can't load AutoCAD, can't reach Oracle, can't run PowerShell installers on Windows. Be explicit about what's "code-level applied" vs. what's "acceptance-tested" — the distinction goes in every phase doc and into `deferred-validation.md`.

### Small `[SuppressUnmanagedCodeSecurity]` traps

The attribute is gone in .NET 8 (Code Access Security removed). Stripping it is mechanical, but `sed` patterns must catch BOTH the bare `[SuppressUnmanagedCodeSecurity]` and the fully-qualified `[System.Security.SuppressUnmanagedCodeSecurity]` form. Verify with a final grep.

### Version-pinned native APIs

Watch for things like `acdb17.dll` (AutoCAD 2007's database DLL persisting in code through accident-of-history). The number is the host major-version: AutoCAD 2025 = `acdb25.dll`. Mangled C++ entry-point names also change per host version — capture from `dumpbin /EXPORTS` on the target host.

### "Hardcoded credentials" is overloaded

In ADDS the actual finding was:
1. A C# string `EncryptionKey = "0123…XYZ"` (the hardcoded crypto key)
2. A 13-byte PBKDF2 salt `"Ivan Medvedev"` in a byte-array literal (StackOverflow copy-paste)
3. A `Password=" + var + "` string concat (not actually hardcoded — but reads like it in a grep)

Keep the three concepts separate when planning. They have different fixes (DPAPI, parameterized SQL, refactor connection-string builder).

### "UNC paths" might not be UNC strings

ADDS's "UNC path" finding was actually `MapDrive "M:", "alxapsb12", "Adds"` calls in VBS launchers — the server names exist, but no literal `\\server\share` strings exist in the source. A naive `\\\\X\\Y` regex generates 800+ false positives from LISP-escaped local paths like `"C:\\Data\\file"`.

### Don't ship a generic UNC pattern in the secret-chunker

If the next codebase has actual UNC literals, add a tightened pattern with a string-literal-boundary lookbehind: `(?<=["'\s])\\{2,4}[a-zA-Z][\w-]+\\{1,2}[\w.$-]+`. Otherwise leave it out — false-positive rate is much higher than miss rate.

### The `.format()` `{}` trap

When building reranker prompts (or any prompt that interpolates code), use f-strings, NOT `str.format()`. Chunk content routinely contains literal `{` from C# array initializers, JSON, dict literals — `.format()` raises `ValueError: Single '}' encountered`.

### LISP files (or any embedded scripting) port unchanged

If the host application provides the scripting runtime (AutoCAD provides AutoLISP, SQL Server provides T-SQL, etc.), the secondary-language files copy verbatim to `Updated Files/`. Do NOT try to rewrite them as part of the forced minimum. That's opportunity-backlog territory.

### The forced-vs-optional distinction is what prevents rewrites

Every legacy modernization wants to grow into a from-scratch rewrite. The 2-column "forced vs optional" table is the discipline that stops this. Ship the forced minimum first; iterate on opportunities afterward with the new build infrastructure.

---

## Pre-flight checklist (copy this for each new codebase)

Source archive:
- [ ] `/workspaces/<NAME>/` exists, read-only
- [ ] `git remote set-url --push origin DISABLE_PUSH_TO_READ_ONLY_ARCHIVE`
- [ ] Pinned commit hash recorded
- [ ] File count is plausible (no `node_modules`/`bin/` bulk dump)

Modernized target:
- [ ] `/workspaces/<NAME>_modernized_run<N>/` is a fresh git clone of the source
- [ ] `git remote -v` shows origin pointing at a SEPARATE repo (`BraPil/<NAME>_modernized_run<N>`), not the source archive
- [ ] If new repo doesn't exist: `env -u GITHUB_TOKEN -u GH_TOKEN gh repo create BraPil/<NAME>_modernized_run<N> --private`
- [ ] `archive` remote added with `set-url --push DISABLE_PUSH_TO_READ_ONLY_ARCHIVE`

Analysis workspace:
- [ ] `/workspaces/<NAME>_ALARMv3/` exists with `RUN_PLAN.md` describing the run goal
- [ ] `.alarmv3/policy/autopilot.yaml` defaults verified

ALARMv3 engine:
- [ ] `/workspaces/ALARMv3/.venv/bin/python --version` is 3.12+
- [ ] Ollama running: `curl -s http://localhost:11434/api/tags` lists `nomic-embed-text`
- [ ] `ANTHROPIC_API_KEY` set in environment
- [ ] No stale session: `ls /workspaces/<NAME>_ALARMv3/.alarmv3/sessions/` is empty
- [ ] Engine settings load-bearing knobs verified (full-archive-run.md §1.5)

Phase 0 unblocking decisions:
- [ ] Target framework / runtime / host versions confirmed
- [ ] Internal corporate libs .NET 8 (or equivalent) status confirmed
- [ ] Authentication mode decided
- [ ] Backwards-compat scope confirmed
- [ ] OS support matrix decided
- [ ] Source-control history migration decision made
- [ ] Deployment scope (single dev install vs. broad rollout) decided

Output:
- [ ] `BraPil/ALARMv3/wiki/project/<NAME>-modernization-plan.md` (the plan)
- [ ] `BraPil/<NAME>_modernized_run<N>/Updated Files/` (the migrated codebase)
- [ ] `BraPil/<NAME>_modernized_run<N>/Documentation/` (phase records)
- [ ] `BraPil/<NAME>_modernized_run<N>/Documentation/deferred-validation.md` (the on-host TODO list)
- [ ] `BraPil/<NAME>_ALARMv3/` (the analysis state, RUN_PLAN, wiki summary, recommendations)

When all boxes above are checked AND every item in `deferred-validation.md` has been verified on the target host, the migration ships.
