# Project completion

The goal is to finish the application described in the [design](design.md) and [roadmap](roadmap.md), across all eight otelc languages. The delivered scalar generator is a foundation. Passing its maintained examples does not complete the broader project.

This checklist records the acceptance boundary. A row becomes complete only after implementation, negative controls, source preservation, current documentation and published exact-revision evidence cover the whole requirement. Optional features remain explicitly optional; unavailable requested capabilities remain visible.

| Requirement | Current evidence and remaining work |
| --- | --- |
| Source-wide callable accounting in all eight languages | Syntax inventories exist. Semantic/build inclusion, generic instances, inherited/private access and dependencies need project-aware adapters. |
| Actual project configuration | In progress: a validated, frozen policy for selection, inputs and execution budgets. Build, fixture and observation contracts must all be consumed by the application. |
| Real repository build/dependency integration | Open: compilation databases, Cargo targets/features, Go packages, Java classpath/modules, Python packages and Node ESM/CommonJS/TypeScript project context. |
| Generated concrete inputs and domain fixtures | Scalar inputs exist. Add explicit domains, factories, complex arguments, reviewed preconditions and shared corpus materialisation. |
| Constructors, receivers and mutable arguments | Open: independently reconstructed fixtures, instance method calls and declared access routes for every adapter. |
| Stateful, asynchronous and resource sequences | Fixed context/lifetime diagnostics exist. Generated construction/action/yield/completion/cleanup sequences and bounded schedules remain open. |
| Typed observation and graph comparison | Shared Rust versioned graphs, alias/cycle matching, initial-state validation, repeat checks and field-path differences are implemented. Generated-worker conversion, complete qualified language codecs and executed graph-producer qualification remain open. |
| Configured globals/statics and instance roots | Open beyond existing scalar and Python/Node module roots: richer native/Java/Go/Rust objects, imported roots and explicit opaque/unobserved dimensions. |
| Declared filesystem, fixture/network and resource effects | Open: independent fixtures, bounded effect capture and explicit observation contracts. Transient writes require a separate supported mode. |
| Matched baseline/on and declared off/fault lanes | Repeated baseline/on is implemented. Qualify the actual provider capabilities for disabled recording/export and optional exporter faults without substituting lanes. |
| Per-case instrumentation and transport witness | Actual local decoding exists. Extend it to each new callable/build/sequence and retain actual selection/transform provenance, health and loss counters. |
| Source/dependency preservation and private workspaces | Existing source/snapshot/ownership guards are tested. Extend them to every new build graph, dependency fixture and promotion action. |
| Isolation, repeatability and resource budgets | Bounded independent processes exist. Add configured budgets/repeats, reproducible seeds, initial fixture equivalence, external fixture isolation and separately qualified container execution. |
| Counterexample shrinking and replay | Frozen replay/export exist. Add deterministic typed shrinking which retains the original failure and all comparison/witness preconditions. |
| Inventory, observations and reviewable reporting | JSON evidence and standalone HTML/JUnit presentation expose case/inventory denominators, differences and strict gaps. The typed comparator supplies field differences; generated graph presentation, redaction/unobserved fields and richer per-capability statuses remain open. |
| Retained/promoted framework projects | External unittest/export exist. Complete the roadmap's independent framework projects, dependencies, dry-run promotion plans and explicit apply operations. |
| Actual production/shipping workload qualification | Open: exact artefact hashes, release recipes, managed transforms/loader provenance, representative workloads and independently recorded shipping observations. |
| Functional and performance gates | Functional scalar checks exist. Add independently reported application overhead/resource budgets and qualification for optional live toggles/fault scenarios. |
| Common eight-language and platform qualification | Scalar macOS ARM64 fixtures pass. Extend the shared defect corpus to every new capability; qualify each published OS/architecture/toolchain combination through actual execution. |
| Installation, release and usable demonstration | Open: reproducible installation/release assets, dependency scanning and a real mixed-language application demonstration, including repeat execution and cleanup. |
| Review, CI, documentation and repository hygiene | Required protected checks exist. Every delivery must retain review, green final-head/main checks, current guidance and clean source/branches. |

The project is not complete while any required row is open or only partly qualified. The result remains **equivalence over these tests and observations**; exhaustive correctness of every possible input or schedule is not a deliverable.
