# ADDS modernization plan — AutoCAD Map 3D 2025 / Oracle 19c / .NET 8

> **Status**: approved · execution started 2026-04-29
> **Scope**: forced-minimum migration (11-week target) + ranked opportunity backlog
> **Source-of-truth**: this page. Phase-specific runbook entries live under `wiki/runbooks/`.

## Executive summary

ADDS is a ~7,500-line C# AutoCAD plugin (`Adds.dll`) plus ~25,000+ lines of AutoLISP that operates inside AutoCAD 2019. It connects to Oracle for a division-mapping data model (Alabama Power, Georgia Power) and is deployed via legacy VBScript+`.Cmd` Xcopy chains from a network share. The modernization is **forced by AutoCAD 2025**: it is the first version to ship on .NET 8, which means moving to .NET 8 is non-negotiable to stay on a supported AutoCAD. Oracle 19c is a separate but compatible track.

This is **not a rewrite**. The C# is small, the LISP is large but largely portable as-is (AutoCAD 2025 still hosts AutoLISP), the Oracle SQL is mostly stable, and the AutoCAD managed API has been backwards-compatible across versions. **Most of the work is plumbing, security, and deployment** — not application logic.

## Current state baseline

| Layer | What's there now |
|---|---|
| Build / SLN | Visual Studio 2012 solution format · TFS 2012 binding · MSBuild ToolsVersion 12.0 · raw `<Reference HintPath>` (no NuGet) |
| Target framework | .NET Framework 4.7 · `OutputType=Library` · `PlatformTarget=x64` |
| AutoCAD bindings | accoremgd / acdbmgd / acmgd v20.1.0.0 (AutoCAD 2019) · Autodesk.AutoCAD.Interop & Interop.Common with `EmbedInteropTypes=True` |
| Oracle bindings | `Oracle.DataAccess` (ODP.NET classic, unmanaged) v2.112.1.0 — Oracle 11.2 client · references local file under `Southern\Oracle\Client11_2_Win64\odp.net\bin\2.x\` |
| Internal SoCo libs | `ScCoolSecurityNET` v4.0 (GAC) · `ScCoolWindows` v4.0 (GAC) |
| Plugin entry | `public partial class Adds : Acad.IExtensionApplication` (`adds.cs:41-45`). `Initialize()` only writes a status message |
| LISP/C# bridge | 4 P/Invoke entry points marked `[SuppressUnmanagedCodeSecurity]`: `acedGetSym`, `acedPutSym` (`acCore.dll`), `acedEvaluateLisp` (`acad.exe`, mangled C++ name), `ads_queueexpr` (`accore.dll`) |
| Oracle access | `OracleConnection` / `OracleCommand` / `OracleDataAdapter.Fill()` · `Pooling=false` · mixed parameterized (`:name`) and concatenated SQL · static `Adds._strConn` field shared globally |
| Authentication | WinForms `frmLogin` → live `OracleConnection.Open()` · service-account fallback uses hardcoded `Addslodr21dv` / `Addslodr22dv` decoded via custom `Encrypt`/`Decrypt` (AES + PBKDF2 with hardcoded `EncryptionKey = "0123…XYZ"` and 13-byte salt `"Ivan Medvedev"`) |
| UI | WinForms only · BindingSource → DataTable pattern · no third-party controls |
| Threading | None. Single `Thread.Sleep(5000)` workaround in `SavePanel` |
| LISP | ~25,000+ LOC: `Utils.Lsp` (12,802) · `Acad.Lsp` (7,764) · `GET_INIT.LSP` (3,240) · `Common.Lsp` (362) · plus ~20 smaller files |
| Map 3D specific code | None active. One commented-out `// using AcadGIS = Autodesk.Gis.Map;` in `jigs.cs` |
| Config | INI files, XML lookups, hardcoded UNC `S:\Workgroups\APC Power Delivery\…` paths, `MapDrive "M:", "alxapsb12", "Adds"` in VBS |
| Deployment | `.vbs` launcher → `MapDrive` → `.Cmd` `Xcopy` · separate W7 / W10 variants |
| Tests | None. Some `(defun Test ...)` and `C:TestProfs` ad-hoc LISP routines |
| Third-party | DOSLib (multiple versions: 14, 17, 2k) |

## Target state

| Layer | Target |
|---|---|
| Build | Visual Studio 2022 · SDK-style `.csproj` · NuGet `PackageReference` only · Git |
| Framework | `<TargetFramework>net8.0-windows</TargetFramework>` |
| AutoCAD | accoremgd / acdbmgd / acmgd from AutoCAD 2025 (`HintPath` resolved via `$(AutoCADInstallDir)`) |
| Oracle | `Oracle.ManagedDataAccess.Core` 23.x — pure-managed, **no Oracle Client install required** |
| Plugin entry | Same `IExtensionApplication` pattern. Drop `[SuppressUnmanagedCodeSecurity]` (no-op on .NET 8). Update `acedEvaluateLisp` mangled name |
| Oracle access | Parameterized SQL only · `using` on every disposable · pooling enabled · `IConfiguration` for connection strings |
| Authentication | DPAPI for any local credential cache, replacing hardcoded `EncryptionKey` |
| Config | `appsettings.json` + `appsettings.{Division}.json` · zero hardcoded UNC paths in source |
| Deployment | PowerShell installer (`Install-Adds.ps1`) replacing the VBS+Cmd chain · single script handles W10/W11 (W7 dropped) |
| Tests | xUnit `Adds.Tests` project · GitHub Actions CI |

## The single most important strategic insight

Distinguish **forced** changes (cannot ship without them) from **opportunistic** changes (can defer). Ship forced changes first as a single migration release, then iterate on opportunities with the new build infrastructure.

| Forced by target | Optional improvement |
|---|---|
| .NET 4.7 → .NET 8 | God-object `Adds` partial class refactor |
| `Oracle.DataAccess` (unmanaged 32-bit) → `Oracle.ManagedDataAccess.Core` | SQL injection cleanup beyond forced minimum |
| AutoCAD 2019 → 2025 references | LISP → C# rewrites |
| VS 2012 SLN → SDK-style csproj | WinForms → WPF/MAUI |
| TFS → Git | Async/await adoption |
| `acedEvaluateLisp` mangled-name update | Replace WinForms |
| `[SuppressUnmanagedCodeSecurity]` removal | Test infrastructure beyond floor |
| GAC references → file/NuGet | DPAPI or Key Vault for secrets |

## Phased plan (eleven-week target for forced minimum)

### Phase 0 — Pre-work (1–2 weeks, unblocking)

Environment, access, and decisions that must land before code touches:

- [ ] AutoCAD Map 3D 2025 install on a developer workstation
- [ ] Oracle 19c connectivity verified from that workstation against a non-prod schema
- [ ] SoCo internal NuGet feed access confirmed, OR definitive answer that ScCoolSecurityNET / ScCoolWindows are .NET-Framework-only and need replacement
- [ ] Decision on internal SoCo libs: (a) wait for SoCo .NET 8 builds, (b) replace with open-source equivalents, (c) wrap behind interface and stub for non-SoCo dev
- [ ] AutoCAD 2025 `acad.exe` exports captured via `dumpbin /EXPORTS` to get the new mangled name for `acedEvaluateLisp`

**Acceptance**: a developer can build a hello-world AutoCAD 2025 plugin against .NET 8 and load it in AutoCAD 2025 reading from Oracle 19c.

### Phase 1 — SDK-style project + .NET 8 retarget (2–3 weeks)

1. Convert `Adds.csproj` to SDK-style with `net8.0-windows` TFM, `UseWindowsForms=true`, `Platforms=x64`.
2. Move all references to `<PackageReference>` or `<Reference>` with `<Private>false</Private>` for AutoCAD assemblies (must NOT ship them — AutoCAD provides at runtime).
3. Replace `Oracle.DataAccess` with `<PackageReference Include="Oracle.ManagedDataAccess.Core" Version="23.*" />`.
4. Update AutoCAD `HintPath`s from 2019 to 2025; resolve via `$(AutoCADInstallDir)` env var.
5. Drop `[SuppressUnmanagedCodeSecurity]` everywhere.
6. Update `acedEvaluateLisp` P/Invoke entry point with the captured mangled name from Phase 0.
7. Remove all `<SccProjectName>SAK</SccProjectName>` and TFVC traces.
8. Smoke-test: NETLOAD `Adds.dll` in AutoCAD 2025, run `(MyLoginObj_2012 …)`, verify Oracle round-trip.

### Phase 2 — Forced security minimums (1 week)

1. Replace every concatenated SQL with parameterized SQL. Known sites: `frmLogin.cs:244, 342`, `adds.cs:2338, 2368`, `acadline.cs:846`, `acadsymbol.cs:1333, 1354`, plus anything else flagged by `secret_pattern` chunks.
2. Wrap every `OracleCommand` / `OracleDataReader` / `OracleConnection` in `using`.
3. Replace hardcoded `EncryptionKey = "0123…XYZ"` + 13-byte salt with **DPAPI** (`ProtectedData.Protect/Unprotect`).
4. Move connection-string template to `appsettings.json`; secrets via DPAPI or Key Vault.
5. Remove hardcoded `Addslodr21dv` / `Addslodr22dv` service-account names.
6. Strip PII from source (hardcoded employee names + GPS in `OSDMapFO.Lsp` → Oracle table).

### Phase 3 — Modern deployment (2 weeks)

1. `Deploy/Install-Adds.ps1`: detects AutoCAD 2025, `robocopy /MIR /XO`, configurable source from JSON, ACLs via `Set-Acl` (per-user, not Users group), creates `appsettings.json` from template, registers `Adds.dll` for NETLOAD.
2. Single script handles W10 and Windows 11 (W7 dropped — out of AutoCAD 2025 support anyway).
3. `Deploy/Uninstall-Adds.ps1` for clean removal.
4. Optional: WiX/Advanced Installer MSI for proper Add/Remove Programs entry.

### Phase 4 — Configuration externalization (1 week)

1. All hardcoded UNC paths move to `appsettings.json`.
2. `addslookups.xml` content becomes `appsettings.{Division}.json`.
3. Division→code mapping moves from C# `switch` to a JSON-loaded `Dictionary<string,string>`.
4. Hardcoded GPS / employee data in `OSDMapFO.Lsp` moves to an Oracle table.

### Phase 5 — CI / test floor (1–2 weeks)

1. `Adds.Tests` xUnit project.
2. Mockable Oracle layer behind `IOracleDataAccess` interface.
3. GitHub Actions: `dotnet build`, `dotnet test`, `dotnet format --verify-no-changes`.
4. Documented manual smoke-test plan for AutoCAD-hosted parts.

## Prioritized upgrade-opportunity backlog (post-shipping)

After Phases 0-5 ship, the following opportunities are ranked by ROI. None are required for the modernized release.

| Rank | Opportunity | Effort | Why this rank |
|---|---|---|---|
| 1 | Decompose god-object `Adds` partial class into single-responsibility services (`OracleService`, `AuthService`, `LispBridge`, `PaletteRegistry`, `DivisionRouter`) | L | Highest leverage refactor — enables testability and onboarding |
| 2 | Full audit of remaining concatenated SQL beyond Phase 2 forced-minimum scope | M | Long tail of injection sites |
| 3 | Replace global-state mutation in LISP `S:err` with stack-based context manager pattern | M | Most fragile runtime path; one bad exception leaves state corrupted |
| 4 | Structured logging via `Microsoft.Extensions.Logging` with file + Application Insights sinks | S | Currently zero observability |
| 5 | Dapper + record types replacing `DataTable` for read-only queries | M | Faster, leaks less, type-safe; defer UI-bound queries |
| 6 | AutoCAD 2025 plugin bundle (PackageContents.xml) replacing `acad.lsp` netload chain | M | Modern AutoCAD plugin model |
| 7 | DOSLib version consolidation (current version, drop 14/17/2k variants) | M | Three-versioned dependency is a code smell |
| 8 | LISP-side scripted-launch tests via `acad /b` batch mode | M | Without LISP tests, refactoring 25k LOC is high-risk |
| 9 | Async UI on long Oracle queries (`Task.Run` + `Invoke` back to UI thread) | M | UX win, low risk if scoped |
| 10 | WinForms → WPF or MAUI Blazor Hybrid | XL | Aesthetics until WinForms is actually deprecated |
| 11 | Move LISP common utilities (`Utils.Lsp`'s 12,802 lines) into C# where AutoCAD-loop-independent | XL | Long-term modernization; only after C# test floor is solid |
| 12 | Replace `addslookups.xml` lookup with database-backed config table | M | One source of truth |
| 13 | LISP linter / formatter pass on the 25k LOC | L | Hygiene |
| 14 | Replace IE-only HTML frameset templates (PTW templates) with modern HTML | M | Likely dead code |

## Risk register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| `ScCoolSecurityNET` / `ScCoolWindows` have no .NET 8 build | High | Critical | **Block on this in Phase 0.** Get definitive answer before timeline commit. Wrap behind interface as fallback |
| `acedEvaluateLisp` P/Invoke breaks silently with new mangled name | Medium | High | Phase 1 acceptance test must call this path. Capture exports early |
| Oracle 19c rejects legacy auth mode used by ODP.NET classic | Low | Medium | Confirm Managed driver against actual prod 19c in Phase 0 |
| AutoCAD 2025 deprecates a managed API ADDS uses | Low | Medium | Read AutoCAD 2025 .NET migration guide before Phase 1 |
| LISP code paths assume Windows 7 (`OS = "WIN7"` checks) break on W10/W11 | Medium | Low | Audit `Acad.Lsp` for OS branches; W7 EOL anyway |
| Deployment-pipeline change blocked by SoCo desktop policy | Medium | High | Engage desktop-deploy team in Phase 0. Authenticode-sign all PS1 |
| `EncryptionKey` reused by other internal tools reading same encrypted blobs | Low | High | Audit before swapping. If shared, requires re-encryption migration |
| 13-byte salt change makes existing encrypted credentials unreadable | High (if persisted) | Medium | If only used for live-session credentials, no migration. Otherwise add decrypt-old + encrypt-new step on first run |

## Cost & timeline

| Phase | Duration | Cumulative |
|---|---|---|
| Phase 0 — pre-work | 1-2 weeks | 2 weeks |
| Phase 1 — .NET 8 retarget | 2-3 weeks | 5 weeks |
| Phase 2 — security minimums | 1 week | 6 weeks |
| Phase 3 — modern deployment | 2 weeks | 8 weeks |
| Phase 4 — config externalization | 1 week | 9 weeks |
| Phase 5 — CI / test floor | 1-2 weeks | 11 weeks |
| **Modernized ADDS shipping** | | **~11 weeks** |
| Backlog item #1 (god-object refactor) | 4-8 weeks | 15-19 weeks |

## Open questions that need decisions before kickoff

1. **`ScCoolSecurityNET` / `ScCoolWindows` .NET 8 status?** — single biggest unknown
2. **Oracle 19c authentication mode** — integrated security/Kerberos, or username+password?
3. **Map 3D vs base AutoCAD 2025 license** — codebase doesn't use Map 3D APIs; is there a licensing reason Map 3D specifically is the target?
4. **Deployment scope** — local-only install, or push to N hundred workstations?
5. **Backwards compatibility with existing ADDS sessions** — does new build need to read drawings/data produced by old?
6. **W7 / W11 support matrix** — assuming W7 dropped, is W11 22H2 / 23H2 / 24H2 the floor?
7. **TFS history migration** — TFVC history into Git, or source-archive snapshot sufficient?

## See also

- [Full-archive run runbook](../runbooks/full-archive-run.md) — RAG querying patterns and known silent-failure paths
- [project/phase1-implementation.md](phase1-implementation.md) — engine internals
