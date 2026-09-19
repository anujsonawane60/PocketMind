# Architecture

## The two modes

PocketMind decides what to show by looking at the connected drives, not at anything stored
on the host:

```
start
  │
  ├─ no drive carries PocketMind/config/pocketmind.json  → setup mode (the wizard)
  ├─ exactly one does                                    → open it, go straight to chat
  └─ several do                                          → ask which one
```

`AppSession.autobind()` runs this at startup. Binding opens the drive's database, vault, and
model provider; unbinding closes all three so the drive can be ejected cleanly.

## Layout

```
apps/backend/pocketmind/
├── config.py            paths and budgets; nothing is relative to the working directory
├── logs.py              rotating logs with a credential-redacting filter
├── schemas.py           every request and response model
├── main.py              app assembly, origin guard, error translation
├── __main__.py          `python -m pocketmind`
│
├── routers/
│   ├── setup.py         drives, hardware, recommendations, the install job
│   ├── chat.py          conversations and SSE streaming
│   ├── library.py       memories, documents, "what do you know about me?"
│   ├── vault.py         secret storage, gated on a session token
│   └── system.py        state, dashboard, settings, runtime, models, export
│
├── providers/
│   ├── base.py          the LLMProvider protocol (PRD section 68)
│   └── llamacpp.py      llama.cpp: install, start, stop, chat, stream
│
├── services/
│   ├── drives.py        drive detection, eligibility, write-speed probe
│   ├── hardware.py      CPU, RAM, GPU, VRAM, performance rating
│   ├── catalog.py       model catalog, storage budget, recommendation engine
│   ├── downloads.py     resumable, verifiable downloads
│   ├── portable_python.py  bundles an embeddable Python onto the drive
│   ├── installer.py     the checkpointed installation job
│   ├── data.py          SQLite + FTS5
│   ├── rag.py           document parsing, chunking, indexing
│   ├── assistant.py     retrieval and prompt construction
│   ├── vault.py         Argon2id + AES-GCM secret storage
│   └── session.py       the running application's state
│
└── static/              the interface: no build step, no external requests
```

## Layering

```
routers/  →  services/session  →  services/*  →  providers/
                                      ↑
                                  schemas.py
```

Routers contain no logic beyond translating HTTP to a service call. Services never import
FastAPI, which is why they are directly testable and could back a desktop shell later.

## Why llama.cpp rather than Ollama

The PRD names Ollama as the first provider. Ollama installs itself onto the host machine and
keeps models in a host-side directory, which conflicts with the product's central promise
that the drive carries everything. llama.cpp ships as a self-contained set of binaries that
can be unpacked onto the drive and run from there with no host installation at all.

The `LLMProvider` protocol exists so this is a swap rather than a rewrite. An
`OllamaProvider` implementing the same eight methods would drop in without touching a router.

## Retrieval

There is no embedding model. Documents are split into overlapping passages and indexed with
SQLite's FTS5 extension, ranked by BM25:

```
document → parse → chunk (900 chars, 150 overlap) → chunks table + chunks_fts
question → tokenise → quote each term → MATCH → bm25() → top N passages
```

This is a deliberate trade. A vector index would rank better on paraphrased questions, but
it costs a second model download (another ~100 MB plus a second server process on a device
where RAM is already the binding constraint) and a rebuild of the whole index whenever the
embedding model changes. BM25 over well-sized chunks is strong on the keyword-heavy
questions people actually ask their own notes, needs no extra download, and works offline
from the first second.

The upgrade path is open: `search_chunks` is the only retrieval entry point, so adding a
vector index behind it — or a hybrid re-rank — does not change anything above it.

Each term is quoted before being passed to `MATCH`, which makes FTS5 operator characters in
user input inert. A question containing `*`, `NOT`, or a stray quote cannot break search.

## Prompt construction

```
question
   ↓
retrieve relevant memories  (ranked, capped by settings.memory_results)
retrieve relevant passages  (ranked, capped by settings.retrieval_results)
   ↓
system prompt + memories + passages + last 12 messages + question
   ↓
local model
```

The whole memory database is never injected. `assistant.py` has no import path to the vault,
which is asserted by a test rather than left as a convention.

## Installation

`InstallJob` runs ten steps in a worker thread, writing a checkpoint after each:

```
layout → app → python → runtime → model → database → vault → config → launcher → verify
```

Every step is idempotent, and the checkpoint records which ones finished. Resuming re-reads
it and skips completed work; a partial model download resumes from its byte offset via an
HTTP Range request. The checkpoint is invalidated if the chosen model changes.

Bundling Python is best-effort. If it fails the install still completes and the generated
launcher falls back to a Python on the host, with the difference reported to the user.

The final step loads the model and asks it one question. An installation that cannot answer
is reported as failed rather than as success.

## Security boundaries

**Vault.** Argon2id (64 MiB, t=3, p=4) derives a key from the master password; the entry list
is encrypted as a single AES-GCM payload with the KDF parameters as additional authenticated
data, so they cannot be downgraded in place. Entry names are inside that payload — only the
entry count is readable while locked. Writes go to a temporary file, fsync, then replace,
keeping the previous version as a backup, because removable drives get unplugged.

**Session token.** Unlocking issues a random token held only in memory, required by every
vault route and compared with `hmac.compare_digest`. The browser keeps it in a JavaScript
variable, never in localStorage, so nothing survives on a borrowed machine.

**Origin guard.** Every state-changing request with a foreign `Origin` header is rejected.
Without this, a page open in the same browser could drive the local API.

**Logging.** A filter scrubs credential-shaped strings on the way out. Message and document
contents are described by length, never reproduced.

## Constraints the recommender enforces

A model is only offered if it clears all four of these, each with a message saying which one
it failed:

1. **Free space** — model + engine + workspace + a 2 GB reserve must fit.
2. **Single-file size** — FAT-formatted drives cannot hold a file of 4 GB or more, whatever
   their free space says. Many USB sticks ship this way.
3. **Memory** — the model's working set must fit in RAM with 3 GB left for the operating
   system, not merely in total RAM.
4. **Reachability** — the download URL is checked with a HEAD request before it is offered.

Ranking then weighs capability, how well the model matches the use cases the user selected,
and how fast it will actually feel on this hardware. Speed carries as much weight as the
match, because a larger model answering at a word per second is worse advice than a smaller
one that keeps up.

## Host preflight

Two host conditions stop the engine from ever running, and both are detected before a
multi-gigabyte download rather than after:

* **Smart App Control / WDAC.** Read from
  `HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState`. When
  enforcing, Windows refuses to load the unsigned llama.cpp binaries; the loader returns
  `0xC0E90002` and the process produces no output at all. The wizard reports this on the
  hardware screen, and the installer offers to build the drive anyway for use elsewhere.
* **Anything else that stops the engine.** Immediately after the engine is installed — and
  before the model download — `verify_engine()` runs `llama-server --version` and checks the
  exit code. A machine that cannot run it never costs the user a download.

The engine's own stdout and stderr go to `PocketMind/logs/engine.log` rather than to
`DEVNULL`. This was not the original design; it was added after a failure on real hardware
proved undiagnosable without it.

## Known limitations

- Windows only for now. Drive and GPU detection are the platform-specific parts.
- Retrieval is lexical, not semantic (see above).
- The model catalog is a curated list whose sizes and availability are verified live, rather
  than a full search of a provider's library.
- A compromised host can observe an unlocked vault. This is inherent, and documented.
