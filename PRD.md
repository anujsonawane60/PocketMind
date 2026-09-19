# PocketMind

### Your AI. Your memories. Your drive.

**Product Requirements Document (PRD)**
**Version:** 1.0
**Status:** Proposed
**Product Type:** Open-source portable private AI platform
**Primary Platform:** Windows initially
**Future Platforms:** Linux, macOS, Android
**Repository:** `pocketmind`

---

# 1. Product Overview

PocketMind is an open-source application that transforms a USB drive into a **portable private AI assistant**.

A user clones the PocketMind repository, runs the setup application, selects a USB drive, and follows a guided onboarding process.

PocketMind then:

1. Detects available removable drives.
2. Allows the user to select their AI drive.
3. Inspects the drive.
4. Warns if existing data will be deleted.
5. Optionally formats/prepares the drive.
6. Detects the host computer's hardware capabilities.
7. Calculates available storage.
8. Retrieves compatible AI models from supported model registries.
9. Recommends models based on available storage and host hardware.
10. Installs the AI runtime and selected models onto the USB drive.
11. Creates the private data vault.
12. Initializes local memory and RAG.
13. Creates a portable AI environment.
14. Launches the PocketMind interface.
15. Provides an onboarding tutorial explaining how to use the system.

The final result is a USB drive that contains the user's:

* Local AI runtime
* AI model(s)
* Personal memories
* Local documents
* RAG index
* Encrypted secrets
* Configuration
* Application data

The goal is that the user's personal information remains local and does not need to be sent to a cloud AI provider.

---

# 2. Problem Statement

Modern AI assistants are powerful, but users may hesitate to provide highly personal information to cloud-based services.

Examples include:

* Personal notes
* Private relationships
* Personal goals
* Journals
* Password-related information
* API keys
* Recovery codes
* Private documents
* Financial records
* Business information
* Personal memories

Users need a way to have an AI assistant that can understand their personal information while keeping that information under their control.

Existing local LLM tools generally focus on:

* Running models
* Developer workflows
* Chat interfaces
* Model management

They do not necessarily provide a complete **portable personal AI vault experience**.

PocketMind combines:

> **Portable storage + local AI + encrypted personal memory + RAG + guided setup**

into one product.

---

# 3. Product Vision

> Make personal AI as portable as carrying a USB drive.

A user should be able to carry their AI assistant with them.

The conceptual experience is:

```text
Take USB
   ↓
Plug into computer
   ↓
Launch PocketMind
   ↓
Unlock vault
   ↓
Chat with your AI
   ↓
Access your memories/documents
   ↓
Everything remains local
```

---

# 4. Core Principles

## 4.1 Local-first

Personal data should remain on the user's device.

The application should not require a cloud AI provider for its core functionality.

---

## 4.2 User-controlled

The user decides:

* Which drive to use
* Which model to install
* What information to store
* What information to delete
* Which documents to index
* Which secrets are protected
* Whether internet access is allowed

---

## 4.3 Secure by design

Sensitive information must not simply be stored as plaintext files.

The system should separate:

```text
Normal AI Memory
        +
Private Documents
        +
Secret Vault
```

The Secret Vault should have stronger access controls than ordinary AI memory.

---

## 4.4 Portable

The application should be designed around the concept:

> “My AI environment travels with me.”

The USB should contain the necessary application data and models wherever technically feasible.

---

## 4.5 Hardware-aware

The setup application must not blindly install a model.

It should understand:

* Available USB storage
* Available system RAM
* CPU
* GPU
* GPU VRAM
* Operating system
* Architecture

and recommend models accordingly.

---

# 5. Target Users

## Primary User

A technically comfortable individual who wants:

* Private AI
* Local LLM
* Personal memory
* Portable AI
* Offline access
* Private document search

## Secondary Users

### Developers

Use PocketMind for:

* Coding assistance
* Project documentation
* Local knowledge bases
* API documentation
* Git repositories

### Students

Use it for:

* Notes
* Books
* Study material
* Personal learning history
* Offline tutoring

### Privacy-conscious users

Use it for:

* Journaling
* Personal information
* Private notes
* Local documents

---

# 6. MVP Scope

The first release should focus on **Windows + USB + local LLM + encrypted memory**.

### MVP includes

* Setup wizard
* USB detection
* Drive selection
* Drive validation
* Formatting/preparation flow
* Hardware detection
* Storage calculation
* Dynamic model discovery
* Model recommendation
* Ollama integration
* Model download
* Portable application installation
* Local chat UI
* SQLite database
* Basic memory
* Basic RAG
* Encrypted secret vault
* First-run tutorial
* Offline operation after installation

### MVP does NOT include

* Automatic USB execution
* iOS support
* Full Android support
* Multi-user accounts
* Cloud synchronization
* Remote access
* Complex autonomous agents
* Automatic password harvesting
* Browser password extraction

---

# 7. High-Level Architecture

```text
                         ┌─────────────────────┐
                         │   PocketMind Setup   │
                         │        Wizard        │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   Hardware Scanner  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   USB Drive Manager │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   Model Discovery   │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   Model Installer   │
                         └──────────┬──────────┘
                                    │
                   ┌────────────────┴────────────────┐
                   ▼                                 ▼
          ┌─────────────────┐               ┌─────────────────┐
          │  Local Runtime  │               │  PocketMind UI  │
          │    Ollama       │◄─────────────►│   Web/Desktop   │
          └────────┬────────┘               └────────┬────────┘
                   │                                 │
                   ▼                                 ▼
          ┌─────────────────┐               ┌─────────────────┐
          │    LLM Model    │               │ Memory / RAG    │
          └─────────────────┘               └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │  Encrypted Vault │
                                            └─────────────────┘
```

---

# 8. Repository Architecture

Proposed repository:

```text
pocketmind/
│
├── apps/
│   ├── setup/
│   │   └── setup wizard
│   │
│   ├── backend/
│   │   └── FastAPI backend
│   │
│   └── frontend/
│       └── React application
│
├── core/
│   ├── hardware/
│   ├── storage/
│   ├── models/
│   ├── runtime/
│   ├── memory/
│   ├── rag/
│   ├── vault/
│   └── security/
│
├── providers/
│   ├── ollama/
│   ├── huggingface/
│   └── future/
│
├── installer/
│
├── scripts/
│
├── docs/
│
├── tests/
│
├── config/
│
├── .env.example
├── README.md
├── LICENSE
└── pyproject.toml
```

---

# 9. Setup Experience

The setup experience is one of the most important parts of PocketMind.

The user should not need to manually understand:

* Ollama
* Model files
* Quantization
* Embeddings
* Vector databases
* Python environments
* Runtime configuration

PocketMind should handle these automatically.

---

# 10. Step 1 — Welcome Screen

```text
┌──────────────────────────────────────────────┐
│                                              │
│                 🧠 PocketMind                │
│                                              │
│         Your AI. Your memories. Your drive. │
│                                              │
│       Build your private AI assistant.       │
│                                              │
│              [ Start Setup ]                 │
│                                              │
└──────────────────────────────────────────────┘
```

Explanation:

> PocketMind installs a local AI assistant and private memory system onto a removable drive.

---

# 11. Step 2 — Detect USB Drives

The application scans connected removable storage devices.

Display:

```text
Available drives

○ USB Drive A
  29.7 GB total
  29.7 GB free

○ USB Drive B
  64 GB total
  18 GB free

Select your PocketMind drive

                 [ Continue ]
```

The application must clearly distinguish:

* Internal system drives
* External drives
* Removable drives

Internal system drives should be protected from accidental selection.

---

# 12. Step 3 — Drive Validation

After selection:

```text
PocketMind Drive

Drive: E:
Capacity: 29.7 GB
Used: 0 GB
Free: 29.7 GB

Status: ✓ Ready
```

If data exists:

```text
⚠ This drive already contains data.

PocketMind recommends using a dedicated drive.

Choose:

[ Keep Data & Use Available Space ]

[ Erase Drive & Prepare for PocketMind ]

[ Cancel ]
```

---

# 13. Formatting Safety

Formatting must be considered a destructive action.

The UI should require explicit confirmation.

Example:

```text
⚠ WARNING

Formatting this drive will permanently delete
the existing data.

Drive:
E:\

Data detected:
8.4 GB

[ Cancel ]

[ I Understand — Format Drive ]
```

For additional safety:

* Require typing `ERASE`
* Show drive label
* Show capacity
* Require confirmation

The application must never silently format a drive.

---

# 14. Step 4 — Hardware Detection

PocketMind analyzes the host machine.

```text
Analyzing your computer...

✓ Operating System
✓ CPU
✓ RAM
✓ GPU
✓ GPU VRAM
✓ Architecture
✓ Available storage
```

Example:

```text
Your Computer

CPU: Intel Core i7
RAM: 16 GB
GPU: RTX 3060
VRAM: 12 GB

PocketMind performance profile:

★★★★★
```

The performance rating should be descriptive rather than misleading.

---

# 15. Step 5 — Model Discovery

PocketMind retrieves model metadata from supported providers.

Initial provider:

**Ollama**

Future providers:

* Hugging Face
* llama.cpp model sources
* Additional model registries

Ollama's public model library is continually changing, so PocketMind should retrieve model metadata dynamically rather than shipping a permanently hard-coded list.

---

# 16. Model Recommendation Engine

The application calculates:

```text
Available USB storage
+
System RAM
+
GPU VRAM
+
CPU capability
+
Model size
+
Model format
+
Context requirements
```

Then produces recommendations.

Example:

```text
Recommended Models

┌─────────────────────────────────────────────┐
│ 🟢 Pocket Model                             │
│ 3B                                          │
│                                             │
│ Size: 2.5 GB                                │
│ RAM: ~6 GB                                  │
│ Speed: Fast                                 │
│ Best for: General assistant                 │
│                                             │
│                    [ Select ]               │
└─────────────────────────────────────────────┘


┌─────────────────────────────────────────────┐
│ 🔵 Balanced Model                           │
│ 8B                                          │
│                                             │
│ Size: 5.5 GB                                │
│ RAM: ~10 GB                                 │
│ Speed: Medium                               │
│ Best for: General + coding                  │
│                                             │
│                    [ Select ]               │
└─────────────────────────────────────────────┘


┌─────────────────────────────────────────────┐
│ 🟣 Advanced Model                           │
│ 14B                                         │
│                                             │
│ Size: 10 GB                                 │
│ RAM: ~18 GB                                 │
│ Speed: Slow                                 │
│ Best for: Reasoning + coding                │
│                                             │
│                    [ Select ]               │
└─────────────────────────────────────────────┘
```

The actual available models and sizes should be retrieved dynamically.

---

# 17. Model Selection Strategy

The system should classify models into:

### Tiny

Approximately:

```text
< 2 GB
```

Use case:

* Very low-resource machines
* Basic Q&A

### Small

```text
2–5 GB
```

Use case:

* General assistant
* Basic coding
* Notes

### Medium

```text
5–10 GB
```

Use case:

* General AI
* Coding
* Reasoning
* RAG

### Large

```text
10+ GB
```

Use case:

* Powerful machines
* Advanced reasoning

These are recommendations, not hard rules.

The application should calculate actual requirements for each model.

---

# 18. Storage Budget

PocketMind should reserve space for:

```text
Model
+
Runtime
+
Database
+
Embeddings
+
RAG index
+
Documents
+
Application
+
Future updates
```

Example:

```text
USB capacity:              32 GB
Model:                      5 GB
Runtime:                    1 GB
Application:                500 MB
Embeddings:                 1 GB
Database:                   500 MB
Reserved space:             5 GB
---------------------------------
Recommended available:    ~13 GB
```

The exact calculation should be dynamic.

---

# 19. Step 6 — Installation

After model selection:

```text
Installing PocketMind

✓ Preparing drive
✓ Creating directories
✓ Installing runtime
✓ Downloading model
██████████████████░░ 82%

✓ Installing embeddings
✓ Creating database
✓ Creating encrypted vault
✓ Configuring local API
✓ Creating launcher
✓ Running system test
```

---

# 20. Portable Drive Structure

Final USB structure:

```text
PocketMind/
│
├── app/
│
├── runtime/
│
├── models/
│   └── selected-model/
│
├── data/
│   ├── memory/
│   ├── conversations/
│   ├── documents/
│   ├── embeddings/
│   └── rag/
│
├── vault/
│   └── encrypted.vault
│
├── config/
│
├── logs/
│
├── backups/
│
├── launcher/
│
└── README_START_HERE.html
```

Sensitive data should be encrypted rather than stored as ordinary readable files.

---

# 21. Step 7 — Vault Initialization

The user creates a master password.

```text
Create your PocketMind password

Master Password
[••••••••••••••]

Confirm Password
[••••••••••••••]

Password strength: Strong

[ Create Vault ]
```

The password must never be stored directly.

Use a memory-hard password derivation mechanism such as Argon2id and authenticated encryption for protected data.

---

# 22. Step 8 — Personal AI Setup

The user configures their assistant.

```text
Tell PocketMind about yourself

Name:
[ Anuj ]

What should your AI help with?

☑ Personal organization
☑ Learning
☑ Programming
☑ Projects
☐ Finance
☐ Journaling

[ Continue ]
```

This information becomes initial AI memory.

---

# 23. Step 9 — RAG Setup

The user can optionally import documents.

```text
Build your private knowledge base

Add folders or files:

[ + Add Documents ]

Supported:

PDF
DOCX
TXT
MD
CSV
JSON

Your files remain on this device.

[ Skip for now ]
[ Build Knowledge Base ]
```

Pipeline:

```text
Document
   ↓
Parser
   ↓
Chunking
   ↓
Embedding
   ↓
Vector Index
   ↓
Local Retrieval
   ↓
LLM
```

---

# 24. Step 10 — Installation Complete

```text
🎉 PocketMind is ready

Your private AI assistant is installed.

Drive:
E:\PocketMind

Model:
<selected model>

Storage used:
8.7 GB

Internet required:
No

Your data:
Stored locally

             [ Launch PocketMind ]
```

---

# 25. First-Run Tutorial

After setup:

```text
Welcome to PocketMind

Here are some things you can ask:

"What do you remember about me?"

"Remember that I prefer..."

"Search my documents for..."

"Help me plan my week."

"Summarize my project notes."

"Save this as a private memory."

"What projects am I working on?"
```

---

# 26. Main Chat Interface

The main UI should resemble a modern AI assistant.

```text
┌──────────────────────────────────────────────────┐
│ 🧠 PocketMind                    🔒 Vault Locked │
├───────────────┬──────────────────────────────────┤
│               │                                  │
│ New Chat      │       Good morning, Anuj.        │
│               │                                  │
│ Chats         │       How can I help?            │
│               │                                  │
│ Memory        │                                  │
│               │                                  │
│ Documents     │                                  │
│               │                                  │
│ Vault         │                                  │
│               │                                  │
│ Settings      │                                  │
│               │                                  │
├───────────────┴──────────────────────────────────┤
│ Ask PocketMind...                         ➤      │
└──────────────────────────────────────────────────┘
```

---

# 27. Main Features

## 27.1 Chat

Users can communicate naturally with their local AI.

Examples:

> Explain this Python error.

> Help me plan tomorrow.

> What did I say about my RAG project?

> Search my documents for Pinecone.

---

# 28. Memory System

Memory should support:

### Explicit memory

User:

> Remember that I prefer FastAPI for backend projects.

System:

```text
✓ Saved to memory
```

### Memory retrieval

User:

> What backend framework do I prefer?

AI retrieves:

```text
You previously asked me to remember
that you prefer FastAPI for backend projects.
```

### Memory management

Users can:

* View memory
* Search memory
* Edit memory
* Delete memory
* Export memory

---

# 29. Memory Categories

```text
Memory
│
├── Personal
├── Preferences
├── Goals
├── Projects
├── Learning
├── Work
├── Relationships
├── Important Information
└── Custom
```

Users should be able to create custom categories.

---

# 30. Secret Vault

The Secret Vault is separate from normal AI memory.

Potential entries:

```text
Passwords
API Keys
Recovery Codes
Private Keys
Secure Notes
Credentials
```

The vault should never be automatically exposed to the LLM.

The AI can assist with vault operations through explicit user authorization.

Example:

> Save this API key in my vault.

PocketMind:

> I can save it as a protected secret. Continue?

---

# 31. Vault Security Model

Conceptually:

```text
                    Master Password
                           │
                           ▼
                      Key Derivation
                           │
                           ▼
                    Encryption Key
                           │
                           ▼
                    Encrypted Vault
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          Passwords     API Keys     Secure Notes
```

The plaintext master password should never be persisted.

---

# 32. Offline Mode

Once installation is complete:

```text
Internet disconnected
       ↓
PocketMind
       ↓
Local LLM
       ↓
Local memory
       ↓
Local documents
       ↓
Local vault
       ↓
Works normally
```

Internet should only be required for optional operations such as:

* Downloading models
* Updating the application
* Checking for new models
* Downloading dependencies

---

# 33. Internet / Network Control

PocketMind should expose a clear status:

```text
Network

● Offline Mode
```

or:

```text
● Internet Available

Used for:
✓ Model downloads
✓ Application updates

AI data:
✓ Local
```

Eventually provide a setting:

```text
[✓] Allow Internet Access

Purpose:
☑ Model updates
☑ Application updates
☐ Cloud AI providers
☐ Telemetry
```

Default:

**No telemetry.**

---

# 34. Model Management

The application should support:

```text
Installed Models

✓ Model A
✓ Model B

[ Add Model ]
[ Remove Model ]
[ Update Model ]
[ Set Default ]
```

The user should be able to maintain multiple models if enough storage exists.

Example:

```text
General Assistant
      ↓
General-purpose model

Coding Assistant
      ↓
Coding model

Document Assistant
      ↓
Smaller efficient model
```

---

# 35. Dynamic Model Registry

Instead of hard-coding models into PocketMind:

```text
PocketMind
     │
     ▼
Provider Adapter
     │
     ├── Ollama
     ├── Hugging Face
     └── Future providers
```

Each provider returns standardized metadata:

```text
Model
├── name
├── provider
├── version
├── parameter_count
├── download_size
├── context_length
├── capabilities
│   ├── text
│   ├── vision
│   ├── tools
│   └── reasoning
└── hardware_requirements
```

This allows the model catalog to evolve without requiring a PocketMind release every time a new model appears.

---

# 36. Model Recommendation Engine

Input:

```text
Hardware
+
Storage
+
User selected use cases
```

Output:

```text
Recommended model
Alternative model
Lightweight model
```

Example:

```text
Your goal:
☑ Personal assistant
☑ Coding
☑ Document Q&A

Recommended:

Qwen / compatible 8B model

Why?

✓ Fits your storage
✓ Suitable for coding
✓ Good general assistant
✓ Suitable for RAG
```

The recommendation system should explain its reasoning rather than simply presenting a score.

---

# 37. RAG

PocketMind should provide local document retrieval.

Supported sources:

* PDF
* DOCX
* TXT
* Markdown
* CSV
* JSON
* Code files

Future:

* Images
* Audio transcripts
* Web archives

---

# 38. RAG Interface

```text
Documents

My Documents

├── Python
│   ├── notes.pdf
│   └── fastapi.pdf
│
├── Projects
│   ├── CTOschool.md
│   └── RAG.md
│
└── Personal
    └── notes.txt

[ Add Documents ]
```

---

# 39. Conversation Storage

Chats should be stored locally.

```text
Conversations
├── Today
├── Yesterday
├── Last 7 Days
└── Older
```

Users can:

* Rename
* Delete
* Export
* Search

---

# 40. Data Export

Users should be able to export:

```text
Memory
Conversations
Documents metadata
Vault metadata
Configuration
```

The export itself must warn users if it contains sensitive information.

---

# 41. Backup

PocketMind should provide encrypted backup.

```text
Settings
   ↓
Backup
   ↓
Create Encrypted Backup
```

Backup may contain:

```text
Memory
RAG index
Conversations
Vault
Configuration
```

Models do not necessarily need to be included because they can be downloaded again.

---

# 42. Restore

```text
Restore PocketMind

Select backup:

[ backup-2026-09-16.pmv ]

✓ Memory
✓ Conversations
✓ Vault
✓ Configuration

[ Restore ]
```

---

# 43. Launcher

The USB should have an obvious entry point:

```text
START_POCKETMIND.exe
```

or a platform-specific launcher.

Important:

**USB autorun should not be required.**

Modern operating systems intentionally restrict automatic execution from removable media.

The supported workflow is:

```text
Plug USB
↓
Open drive
↓
Run PocketMind
```

---

# 44. Portability Model

PocketMind should distinguish between:

### Portable data

Must live on USB:

* User memory
* Conversations
* Documents
* Vault
* RAG database
* Configuration
* Model files

### Host-specific components

May temporarily use the host machine:

* OS-specific runtime
* GPU drivers
* Temporary files
* Cache

The architecture should minimize host installation.

---

# 45. Cross-Platform Strategy

## Phase 1

Windows.

## Phase 2

Linux.

## Phase 3

macOS.

## Phase 4

Android.

## Phase 5

Potential iOS companion application.

The data format should remain platform-independent.

---

# 46. Mobile Strategy

Mobile should not depend on USB autorun.

Instead:

```text
PocketMind USB
       │
       ▼
PocketMind Mobile App
       │
       ▼
Import / Connect / Unlock
```

The same encrypted vault format should ideally be readable across supported platforms.

---

# 47. Security Requirements

Security is a first-class product requirement.

### Required

* Encrypted secret vault
* Strong password-derived encryption key
* No plaintext master password storage
* No plaintext secrets in logs
* No secret values in crash reports
* No telemetry by default
* No cloud dependency for core functionality
* Secure deletion where technically feasible
* Automatic vault lock
* Session timeout
* Explicit destructive-action confirmation

---

# 48. Threat Model

PocketMind should explicitly document protection against:

### Lost USB

Attacker obtains the USB.

Expected result:

```text
Encrypted data
+
No master password
=
No useful personal data
```

### Copied USB

Someone copies the complete drive.

Expected result:

Same as above.

### Malicious host

A compromised computer could potentially observe data while PocketMind is unlocked.

Therefore:

> PocketMind cannot guarantee security against a fully compromised host operating system.

This limitation must be documented clearly.

---

# 49. Important Security Boundary

PocketMind should distinguish:

```text
Private AI
```

from:

```text
Password Manager
```

The AI should not automatically know every password.

Instead:

```text
User
 ↓
AI requests secret
 ↓
Vault permission
 ↓
User approval
 ↓
Secret temporarily available
 ↓
Operation
 ↓
Secret removed from AI context
```

The implementation should minimize the exposure of secrets to model context.

---

# 50. Settings

Settings should include:

### AI

* Default model
* Temperature
* Context size
* System prompt
* Response streaming

### Memory

* Memory enabled/disabled
* Auto-memory
* Memory review
* Memory retention

### Vault

* Lock timeout
* Change password
* Backup
* Restore

### Documents

* Indexing
* Embedding model
* Chunk size
* Retrieval count

### Network

* Internet access
* Model updates
* Application updates

### Storage

* Drive information
* Storage usage
* Cleanup

---

# 51. Dashboard

The dashboard should show:

```text
PocketMind

Status
● Running locally

Model
Qwen / selected model

Storage
8.7 GB / 29.7 GB

Memory
248 entries

Documents
37

Conversations
142

Vault
🔒 Locked

Network
Offline
```

---

# 52. Update System

PocketMind should support:

### Application update

```text
Current: 1.2.0
Available: 1.3.0

[ Update ]
```

### Model update

```text
Installed:
Model v1

New:
Model v2

Size:
+500 MB

[ Update Model ]
```

Updates should never automatically delete user data.

---

# 53. Error Handling

Every setup step should have human-readable errors.

Bad:

```text
ERROR 0x80070070
```

Good:

```text
Not enough storage

PocketMind needs:
8.2 GB

Available:
4.1 GB

Please select another drive or choose
a smaller model.
```

---

# 54. Recovery

If installation fails:

```text
Installation interrupted.

PocketMind can:

[ Resume Installation ]

[ Restart Setup ]

[ Clean Installation Files ]
```

The installer should use checkpoints so a failed model download does not require restarting everything.

---

# 55. Logging

Logs should help developers troubleshoot the application.

However:

**Never log:**

* Passwords
* API keys
* Vault contents
* Private messages
* Private document contents

Logs should be safe to share for debugging where possible.

---

# 56. Privacy Principles

PocketMind should follow:

### No telemetry by default

No:

* Analytics
* Advertising
* Tracking
* User profiling

unless explicitly enabled.

### Local-first

User data remains local.

### Transparent networking

The application should clearly indicate when internet connectivity is being used.

---

# 57. Performance Requirements

The application should:

* Start the UI quickly
* Avoid unnecessary background processes
* Stream model responses
* Use incremental indexing
* Avoid rebuilding the entire RAG index unnecessarily
* Detect slow USB storage
* Warn users when storage performance may affect model startup

The LLM's actual inference speed will depend heavily on the host computer, not just the USB drive.

---

# 58. USB Performance Warning

If the selected drive is slow:

```text
⚠ Slow storage detected

PocketMind will work, but model startup and
document indexing may take longer.

A USB 3.x drive or portable SSD is recommended.
```

---

# 59. Acceptance Criteria — Setup

The MVP is successful when:

### Drive

* [ ] Application detects removable drives.
* [ ] Internal drives are clearly protected.
* [ ] User can select a target drive.
* [ ] Existing data is detected.
* [ ] Formatting requires explicit confirmation.
* [ ] Application verifies the drive after preparation.

### Hardware

* [ ] CPU detected.
* [ ] RAM detected.
* [ ] GPU detected where available.
* [ ] VRAM detected where available.
* [ ] Storage detected.

### Models

* [ ] Provider catalog can be queried.
* [ ] Models are filtered by compatibility.
* [ ] Storage requirements are displayed.
* [ ] User can select a model.
* [ ] Model download can resume.
* [ ] Model installation is verified.

### Runtime

* [ ] Local runtime starts successfully.
* [ ] Model responds successfully.
* [ ] No internet is required for normal chat.

---

# 60. Acceptance Criteria — AI

* [ ] User can start a conversation.
* [ ] Conversations are saved locally.
* [ ] User can delete conversations.
* [ ] User can search conversations.
* [ ] User can explicitly save memories.
* [ ] User can view/edit/delete memories.
* [ ] User can add documents.
* [ ] Documents can be indexed.
* [ ] AI can answer using local documents.
* [ ] AI can operate without internet.

---

# 61. Acceptance Criteria — Security

* [ ] Vault is encrypted.
* [ ] Master password is never stored.
* [ ] Secrets are not stored in plaintext.
* [ ] Secrets are excluded from normal logs.
* [ ] Vault can be locked.
* [ ] Vault automatically locks after configurable inactivity.
* [ ] Backup can be encrypted.
* [ ] Restore requires authentication.
* [ ] Destructive operations require confirmation.

---

# 62. Future Features

## Personal Agent

PocketMind could eventually become an actual personal agent.

Example:

> “What should I focus on today?”

The agent could inspect:

* Goals
* Projects
* Tasks
* Notes
* Calendar data imported locally

and generate a plan.

---

## Local Tools

Allow the AI to interact with:

* Local filesystem
* Git repositories
* Python
* Terminal
* Local databases
* Markdown notes

All tools should require explicit permission.

---

# 63. Multiple Personal Agents

Future versions could provide:

```text
PocketMind
│
├── Personal Assistant
├── Coding Assistant
├── Study Assistant
├── Document Assistant
└── Journal Assistant
```

All can share selected memories while maintaining separate contexts.

---

# 64. Plugin Architecture

Future:

```text
plugins/
├── calendar
├── github
├── local-files
├── terminal
├── browser
└── notes
```

Plugins should declare:

* Permissions
* Required capabilities
* Data access
* Network requirements

---

# 65. Agent Permission System

A future agent should not automatically have unlimited computer access.

Use:

```text
AI wants to:
Read ~/Projects/CTOschool

[ Allow Once ]
[ Allow Always ]
[ Deny ]
```

For dangerous operations:

```text
AI wants to execute:

rm -rf ...

⚠ Dangerous operation

[ Cancel ]
```

---

# 66. Product Roadmap

## Phase 1 — Foundation

* Repository
* Setup application
* USB detection
* Drive preparation
* Hardware detection
* Ollama integration
* Model installation
* Basic chat

## Phase 2 — Personal AI

* Memory
* Conversations
* SQLite
* Local embeddings
* RAG
* Documents

## Phase 3 — Security

* Encrypted vault
* Master password
* Auto-lock
* Encrypted backup
* Secure settings

## Phase 4 — Portability

* Better portable runtime
* Linux
* macOS
* Cross-platform data format

## Phase 5 — Agents

* Tool calling
* Local filesystem
* Git
* Terminal
* Permission system

## Phase 6 — Mobile

* Android
* USB/import workflow
* Shared vault format
* Mobile AI interface

---

# 67. Recommended Technology Stack

## Frontend

**React + TypeScript**

UI:

* Material UI
* Tailwind
* or another lightweight component system

## Backend

**Python + FastAPI**

Reason:

* Strong AI ecosystem
* RAG libraries
* Easy local APIs
* Good integration with existing Python tooling

## Local database

**SQLite**

## Vector search

Start with:

**FAISS**

Potential future options:

* LanceDB
* Chroma
* SQLite-based vector extensions

## Local runtime

Initial:

**Ollama**

Ollama provides a local model runtime and model library, making it a reasonable first provider abstraction.

## Embeddings

Provider abstraction:

```text
EmbeddingProvider
├── Ollama
├── SentenceTransformers
└── Future providers
```

## Encryption

Use a well-reviewed cryptographic library rather than implementing cryptography yourself.

---

# 68. Provider Abstraction

Avoid making PocketMind dependent on Ollama internally.

Use:

```text
LLMProvider
│
├── OllamaProvider
├── LlamaCppProvider
└── FutureProvider
```

Interface:

```text
discover_models()
install_model()
remove_model()
start_runtime()
stop_runtime()
chat()
stream_chat()
health_check()
```

This allows PocketMind to change runtimes later without redesigning the entire application.

---

# 69. Core Data Model

Example:

```text
User
 ├── Profile
 ├── Memories
 ├── Conversations
 ├── Documents
 ├── Vault
 └── Settings
```

Memory:

```text
Memory
├── id
├── category
├── content
├── importance
├── created_at
├── updated_at
└── embedding
```

Document:

```text
Document
├── id
├── filename
├── path
├── hash
├── indexed_at
└── status
```

Conversation:

```text
Conversation
├── id
├── title
├── created_at
└── messages
```

---

# 70. Privacy-Safe Memory Retrieval

The assistant should not blindly inject the entire memory database into every prompt.

Instead:

```text
User Question
      ↓
Intent Detection
      ↓
Memory Retrieval
      ↓
Relevant Memories
      ↓
Prompt Construction
      ↓
Local LLM
```

This reduces context usage and limits unnecessary exposure of personal information to the model.

---

# 71. Example User Journey

### Day 1

User downloads PocketMind.

```text
git clone <repository>
cd pocketmind
```

Runs setup.

```text
PocketMind Setup
```

Selects USB.

```text
E:\ 32 GB
```

Chooses:

```text
8B Local Assistant
```

Creates password.

Installation completes.

---

### Day 10

User plugs USB into another laptop.

Runs:

```text
START_POCKETMIND
```

PocketMind starts.

User unlocks the vault.

Asks:

> What was my idea for my personal AI project?

PocketMind retrieves the relevant local memory.

---

### Day 30

User adds:

```text
project-notes/
```

PocketMind indexes them.

User asks:

> Search all my project notes and summarize what I planned for PocketMind.

The answer comes from the local RAG system.

---

# 72. Example Chat Commands

Natural language should be primary.

Examples:

### Memory

> Remember that I want to learn distributed systems.

### Memory retrieval

> What are my current learning goals?

### Documents

> Search my documents for PostgreSQL architecture.

### Projects

> What projects have I been working on?

### Personal planning

> Help me plan my week based on my saved goals.

### Vault

> Save this API key in my secure vault.

### Privacy

> What information do you currently have stored about me?

---

# 73. “What Do You Know About Me?” Feature

A dedicated feature should allow:

```text
What does PocketMind know about me?
```

It should show:

```text
Personal Information
Preferences
Goals
Projects
Learning
Memories
Documents
```

The user can delete anything.

This gives the user visibility into AI memory.

---

# 74. Data Ownership

The product philosophy should be:

> The user owns the data.

PocketMind should not require:

* Account registration
* Cloud account
* Subscription
* API key

for core local functionality.

---

# 75. Open Source Strategy

Recommended license:

**Apache 2.0** or **MIT**

The repository should clearly separate:

```text
PocketMind code
```

from:

```text
Third-party model licenses
```

Model licenses must be respected individually.

PocketMind should display model license information during installation.

---

# 76. README Experience

The GitHub README should make the project understandable in under one minute.

Suggested opening:

```text
# 🧠 PocketMind

### Your AI. Your memories. Your drive.

PocketMind turns a USB drive into a portable,
private AI assistant.

Clone → Run → Select USB → Choose Model → Start.

Your AI runs locally.
Your memories stay locally.
Your documents stay locally.
Your private vault stays encrypted.
```

Then show:

```text
┌─────────────────────────────┐
│        PocketMind           │
│                             │
│  "What do you remember     │
│   about my projects?"      │
│                             │
│  [ Ask PocketMind... ]      │
└─────────────────────────────┘
```

---

# 77. Success Metrics

For the MVP:

### Setup

* User can complete setup without reading technical documentation.
* Setup detects the correct USB drive.
* Model selection provides understandable recommendations.
* Installation can recover from interrupted downloads.

### AI

* Local model responds successfully.
* Chat works without internet.
* Memory retrieval works.
* RAG retrieval works.

### Security

* No plaintext vault data.
* No secrets in logs.
* No telemetry by default.

### Usability

Target:

> A technically capable user should be able to go from cloned repository to first successful local chat in approximately 10–15 minutes, primarily depending on model download speed.

---

# 78. Non-Goals

PocketMind is NOT intended initially to be:

* A cloud AI platform
* A social network
* A SaaS product
* A password manager replacement
* A guaranteed security solution for compromised computers
* An automatic USB autorun mechanism
* A general-purpose operating system

---

# 79. Key Risks

## Risk 1 — USB performance

Slow flash drives can make model startup and indexing unpleasant.

Mitigation:

* Detect storage performance.
* Recommend USB 3.x or SSD.
* Warn users.

## Risk 2 — Model size

Large models may not fit.

Mitigation:

* Dynamic hardware/storage detection.
* Model recommendation engine.

## Risk 3 — Host compatibility

Different computers have different hardware.

Mitigation:

* Runtime abstraction.
* Hardware detection.
* Multiple model options.

## Risk 4 — Security

A stolen unlocked USB could expose information.

Mitigation:

* Encryption.
* Auto-lock.
* Strong authentication.

## Risk 5 — Compromised host

A malicious host can potentially observe an unlocked application's data.

Mitigation:

* Clearly document the threat model.
* Minimize plaintext exposure.
* Provide vault isolation.

---

# 80. MVP Definition

The MVP is complete when a user can perform this entire workflow:

```text
Clone GitHub repository
        ↓
Run PocketMind
        ↓
Setup wizard
        ↓
Detect USB
        ↓
Select USB
        ↓
Check storage
        ↓
Confirm formatting
        ↓
Detect hardware
        ↓
Discover compatible models
        ↓
Select model
        ↓
Download model
        ↓
Install local runtime
        ↓
Create encrypted vault
        ↓
Create local database
        ↓
Start local AI
        ↓
Open chat UI
        ↓
Ask question
        ↓
Receive local response
        ↓
Disconnect internet
        ↓
Ask another question
        ↓
AI continues working
```

That is the **core PocketMind MVP**.

---

# 81. Long-Term Vision

PocketMind should eventually become:

> **A portable operating environment for your personal AI.**

Not simply:

```text
USB + LLM
```

but:

```text
USB
 │
 ├── AI
 ├── Memory
 ├── Knowledge
 ├── Documents
 ├── Secure Vault
 ├── Personal Agents
 ├── Tools
 └── Preferences
```

The user should feel:

> **“This is my AI. It knows what I choose to tell it, my data stays under my control, and I can take it with me.”**

---

# 82. Recommended Initial Repository Milestones

### Milestone 1

```text
Repository
+
Setup UI
+
USB detection
```

### Milestone 2

```text
Drive preparation
+
Hardware detection
```

### Milestone 3

```text
Ollama integration
+
Dynamic model discovery
```

### Milestone 4

```text
Model installation
+
Local chat
```

### Milestone 5

```text
SQLite
+
Memory
```

### Milestone 6

```text
RAG
+
Documents
```

### Milestone 7

```text
Encrypted vault
+
Master password
```

### Milestone 8

```text
Portable launcher
+
Offline validation
```

### Milestone 9

```text
Backup
+
Restore
+
Update system
```

### Milestone 10

```text
Agent framework
+
Tools
+
Permissions
```

---

# 83. Final Product Definition

**PocketMind is an open-source portable private AI platform that allows a user to turn a USB drive into a personal AI environment containing a local LLM, encrypted personal memory, private documents, RAG knowledge, conversations, and a secure vault.**

The setup experience should be:

```text
             CLONE
               ↓
              RUN
               ↓
          SELECT USB
               ↓
        PREPARE / FORMAT
               ↓
        DETECT HARDWARE
               ↓
        DISCOVER MODELS
               ↓
         CHOOSE MODEL
               ↓
        INSTALL EVERYTHING
               ↓
         CREATE VAULT
               ↓
          START AI
               ↓
       🧠 PRIVATE AI
```

The fundamental promise is:

> **Your AI. Your memories. Your drive.**
