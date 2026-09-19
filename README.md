# 🧠 PocketMind

### Your AI. Your memories. Your drive.

PocketMind turns a USB drive into a portable, private AI assistant.

**Clone → Run → Select USB → Choose model → Start.**

Your AI runs locally. Your memories stay locally. Your documents stay locally.
Your private vault stays encrypted. There is no account, no subscription, and no telemetry.

```
┌─────────────────────────────┐
│        PocketMind           │
│                             │
│  "What do you remember      │
│   about my projects?"       │
│                             │
│  [ Ask PocketMind...      ] │
└─────────────────────────────┘
```

---

## Get started

```powershell
git clone <this repository>
cd PocketMind

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

python -m pocketmind
```

Your browser opens the setup wizard. From there PocketMind handles everything:

1. **Choose a drive** — only removable drives and portable SSDs are offered. Internal and
   system drives are shown but cannot be selected.
2. **Answer a few questions** — your name and what you want help with.
3. **Pick a model** — PocketMind inspects your CPU, RAM, and GPU, then recommends models
   that will actually run well, with the reasoning shown.
4. **Create a master password** — this encrypts your vault.
5. **Wait** — PocketMind downloads the inference engine, the model, and a self-contained
   Python onto the drive, creates your database and vault, writes a launcher, and runs a
   test question through the model to prove it works.

There is nothing to configure by hand. No Ollama install, no model files, no quantisation
settings, no vector database setup.

### After setup

Plug the drive into any Windows computer, open it, and run **`START_POCKETMIND.cmd`**.
PocketMind starts and opens straight into your chat — no internet connection required.

---

## What lives on the drive

```
E:\
├── START_POCKETMIND.cmd        ← run this
└── PocketMind\
    ├── app\                    the application itself
    ├── runtime\                inference engine + bundled Python
    ├── models\                 your GGUF model(s)
    ├── data\                   SQLite database, profile
    ├── documents\              imported files
    ├── vault\                  encrypted.vault
    ├── config\                 settings, install checkpoints
    ├── logs\                   redacted, safe to share
    ├── backups\                exports
    └── README_START_HERE.html
```

Nothing personal is written to the host computer. PocketMind finds its installation by
scanning connected drives, so there is no registry key, no AppData folder, and no
configuration left behind.

---

## What it does

**Chat** — streaming replies from a local model, with conversation history saved to the drive.
Rename, delete, and full-text search across everything you have said.

**Memory** — say *"remember that I prefer FastAPI"* and it is saved, categorised, and
retrieved when relevant. View, edit, search, and delete everything from the Memory screen,
or review it all at once under *"What do you know about me?"*.

**Documents** — drop in PDFs, Word files, notes, spreadsheets, JSON, or source code.
They are parsed, split into overlapping passages, and indexed with SQLite FTS5 so answers
cite the specific file and passage they came from.

**Vault** — passwords, API keys, and recovery codes, encrypted with Argon2id + AES-GCM.
Separate from AI memory by design: the assistant has no path to read it, entry names are
encrypted along with values, and the vault relocks itself after inactivity.

**Dashboard and settings** — storage use, model control, retrieval tuning, network policy,
data export, and a safe-eject button.

---

## Design commitments

| Commitment | How it is enforced |
|---|---|
| Never installs to an internal drive | Drive type comes from `GetDriveTypeW` plus the physical disk's bus type; the boot disk is excluded. Covered by tests. |
| Never formats or deletes your files | There is no formatting code anywhere in the repository. PocketMind only creates its own folder. |
| The master password is never stored | Only an Argon2id salt and its parameters are written. Verified by test. |
| Secrets never reach the model | Prompt construction lives in a module that cannot import the vault. Verified by test. |
| The whole memory database is never injected into a prompt | Only ranked, relevant memories and passages are retrieved. |
| No telemetry | There is no analytics code. The only outbound requests are model and engine downloads. |
| Logs are safe to share | A redaction filter scrubs credential-shaped strings; message and document contents are never logged. |

PocketMind **cannot** protect your data on a computer that is already compromised. While the
vault is unlocked, a malicious host can observe it. This is documented rather than hidden.

---

## Requirements

- Windows 10 or 11 (Linux and macOS are planned)
- Python 3.12+ on the computer you run setup from
- A USB drive or portable SSD with roughly 8 GB free
- An internet connection for the one-time download

A USB 3.x drive or portable SSD is strongly recommended. PocketMind measures your drive's
write speed during setup and warns you if it is slow.

**A note on Smart App Control.** Windows 11 ships Smart App Control enabled on many new
machines. It refuses to load software that is not digitally signed, and the llama.cpp
inference engine PocketMind uses is published unsigned — so on such a machine the model
cannot start. PocketMind detects this during hardware detection and tells you before you
download anything, and it will still prepare a drive that works on a computer where Smart
App Control is off. Turning it off is a one-way change: Windows cannot switch it back on
without a reinstall, so PocketMind states the trade-off and leaves the choice to you.

You can check yours under **Windows Security → App & browser control → Smart App Control**.

**A note on drive formatting.** Many USB sticks ship formatted as FAT32, which cannot store
a single file of 4 GB or more — no matter how much free space it reports. PocketMind detects
this and hides models that would not fit, explaining why. Reformatting the drive as **exFAT**
or **NTFS** removes the limit and unlocks the larger models. PocketMind will not reformat it
for you; that is your decision to make in Windows.

---

## Development

```powershell
pip install -e ".[dev]"
pytest                                   # 141 tests
python -m pocketmind --reload            # auto-reload during development
```

API documentation is at `http://127.0.0.1:8000/docs` while the server is running.

See [`docs/architecture.md`](docs/architecture.md) for how the pieces fit together.

---

## Licence

PocketMind is released under the [MIT licence](LICENSE).

AI models carry their own licences from whoever published them. PocketMind shows each
model's licence and requires you to accept it before downloading. Those terms are not
covered by the MIT licence above.
