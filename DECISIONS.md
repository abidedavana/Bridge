# Decisions

Every dependency and every non-obvious judgment call, with the reasoning. The
governing constraints: minimal dependencies, no agent frameworks, every module
readable in one sitting, and nothing that assumes full success.

## Dependencies

Runtime core is deliberately two packages. Everything heavier is an optional
extra so the mock/executor/parser core imports and tests with zero network or
native dependencies.

| Package | Scope | Why this one |
| --- | --- | --- |
| `pydantic` (>=2,<3) | core | Typed config with validation that fails *at startup* with a clear message, never halfway through a run. Already a transitive dep of FastAPI (the dashboard), so it is effectively free. Chosen over hand-rolled dataclass validation to keep the schema declarative. |
| `PyYAML` (>=6,<7) | core | Human-friendly config and scenario files. The one ubiquitous YAML lib; `safe_load` only. |
| `httpx` (optional: `llm`) | brain | OpenAI-compatible HTTP client with timeouts. Deliberately **not** the `openai` SDK: Bridge must talk to Fireworks *and* self-hosted vLLM, and a thin HTTP client avoids vendor-SDK lock-in and shrinks the dependency surface. |
| `paramiko` (optional: `ssh`) | MI300X | Pure-Python SSH/SFTP, so no dependency on a system `ssh` binary (matters for the Docker image and Windows dev). |
| `fastapi` + `uvicorn` (optional: `dashboard`) | demo | Light, async, ships with an OpenAPI schema; pairs with a static frontend. |
| `pytest` (dev) | tests | Standard. |

Explicitly rejected: LangChain / LlamaIndex / any agent framework. The spec
forbids them and they would hide the very state machine the project is meant to
show off. The orchestrator is a plain, explicit Python state machine.

## Judgment calls

**The mock replays captured logs; it does not re-simulate a compiler.** A mock
that tried to model compiler behaviour would be a second, unfaithful compiler.
Instead the mock replays *real* HIPIFY and ROCm diagnostics captured as fixtures,
so the error parser and prompts are exercised against authentic text. The parts
that must be real to be convincing — git commits, file writes, patch application
— really execute locally; only the GPU-bound compile/test is replayed.

**Scenario advancement is commit-driven, not scripted-by-iteration.** A scenario
advances to its next stage when the agent lands an accepted git commit, modelling
"the fix worked, the next error surfaced." This couples the replay to the agent's
*actual behaviour* (a rejected patch does not advance anything) while staying
fully deterministic: a given (scenario, decision-sequence) always replays
identically. `sticky` stages never advance — used for the terminal green state
and for errors the agent cannot clear, which the attempt cap then reports as
`STUCK`.

**Two kinds of mock, named precisely.** The mock *executor* mocks the *hardware*
(GPU/ROCm). The `replay` LLM backend mocks the *brain*. CI pins both, giving a
byte-stable end-to-end run that can assert on exact diffs. A live LLM is
non-deterministic and is therefore never used in CI — only in dev and the demo.
Baking the `replay` backend into the config schema from Milestone 1 avoids a
retrofit when the deterministic end-to-end test lands in Milestone 6.

**Cost accounting has two modes.** A hosted API (Fireworks) bills per token, so
the dashboard shows dollars. Self-hosted vLLM on the MI300X has ~zero marginal
token cost, so dollars would read `$0.00`; the honest and more on-message figure
is throughput (tokens/sec) and GPU-seconds. `CostConfig.mode` (`priced` |
`self_hosted`) selects which, and the schema carries it from Milestone 1.

**Security is a first-class concern, not a costume.** Because Bridge executes
untrusted code and applies model-generated patches, the config schema ships a
`security` section from day one: a writable-path allowlist, a never-touch
protected list, a denylist of dangerous insertions, and a new-file cap. These are
enforced mechanically on the diff (Milestone 3's patch policy engine), so they
hold even under indirect prompt injection. `policy` (don't *cheat* — no editing
tests, no loosening tolerances) is kept separate from `security` (don't cross a
*trust boundary*) because they answer different questions. See THREAT_MODEL.md.

**`python -m bridge` is the documented entry point.** A `__main__.py` lets a
fresh clone run with zero install steps (`pip install pydantic PyYAML` aside);
the `bridge` console script in `pyproject.toml` is the installed equivalent.

## Bugs found and fixed during verification

**Mock command classification matched substrings anywhere (fixed M1).** The mock
executor decided whether a command was a build/test/hipify run by checking
whether words like `test`, `make`, or `ctest` appeared *anywhere* in the command
string. A real git commit with a message like `"fix test 60% tests passed"` was
therefore misclassified as a test run — replayed as a (failing) test and never
actually committed, so the scenario silently failed to advance. This would have
broken the real orchestrator in Milestone 3, where commit messages routinely
contain error-class words. Fixed by classifying on the *leading program token*
only (via `Executor.looks_like`) and always treating `git`/bookkeeping commands
as real. Pinned by `test_commit_message_with_phase_words_runs_for_real` and
`test_classify_uses_leading_token_not_substring`.

## Frozen contracts

**`ErrorClass` (the parser taxonomy) is additive-only (frozen at M2).** It is a
public contract consumed by the M3 diagnosis prompt (which keys its CUDA->ROCm
cheat-sheet by error class) and by the dashboard (which groups the iteration
timeline by class). Day-1 real-log calibration on the MI300X may **add** new
classes or **loosen** existing regexes to match real compiler output, but must
**never rename or remove** an existing class — those consumers would drift out of
sync. Treat the string keys like an API version: additive changes only.
