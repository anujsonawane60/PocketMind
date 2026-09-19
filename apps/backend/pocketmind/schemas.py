"""Request and response models for the local HTTP API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Drives
# --------------------------------------------------------------------------


class DriveKind(StrEnum):
    REMOVABLE = "removable"
    FIXED = "fixed"
    NETWORK = "network"
    CDROM = "cdrom"
    RAMDISK = "ramdisk"
    UNKNOWN = "unknown"


class Drive(BaseModel):
    id: str
    mount_point: str
    label: str | None = None
    filesystem: str | None = None
    kind: DriveKind
    total_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    is_system_drive: bool = False
    volume_serial: str | None = None
    bus_type: str | None = None
    is_external: bool = False
    is_eligible: bool = False
    ineligible_reason: str | None = None
    has_pocketmind: bool = False


class DriveReport(BaseModel):
    """What the drive validation screen shows before anything is written."""

    drive: Drive
    has_existing_data: bool
    existing_entries: list[str] = []
    has_pocketmind: bool
    write_speed_mb_per_second: float | None = None
    is_slow: bool = False
    warnings: list[str] = []
    status: str


class DriveSpeedRequest(BaseModel):
    drive_id: str


# --------------------------------------------------------------------------
# Hardware
# --------------------------------------------------------------------------


class HardwareProfile(BaseModel):
    operating_system: str
    architecture: str
    cpu_name: str
    physical_cores: int | None = None
    logical_cores: int | None = None
    ram_bytes: int = Field(ge=0)
    gpu_name: str | None = None
    gpu_vram_bytes: int | None = Field(default=None, ge=0)
    gpu_vendor: str | None = None
    vram_is_estimate: bool = False
    performance_stars: int = Field(ge=1, le=5)
    performance_label: str
    performance_notes: list[str] = []
    #: Windows Smart App Control / WDAC state. When enforcing, this computer
    #: refuses to load unsigned code, which includes the inference engine.
    app_control: str = "unknown"
    app_control_blocks_engine: bool = False
    blockers: list[str] = []


# --------------------------------------------------------------------------
# Models and recommendations
# --------------------------------------------------------------------------


class ModelTier(StrEnum):
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class ModelCapabilities(BaseModel):
    text: bool = True
    coding: bool = False
    reasoning: bool = False
    vision: bool = False
    tools: bool = False


class ModelInfo(BaseModel):
    id: str
    name: str
    family: str
    provider: str
    parameter_count: str
    quantization: str
    download_size_bytes: int = Field(ge=0)
    size_is_estimate: bool = True
    context_length: int
    tier: ModelTier
    capabilities: ModelCapabilities
    min_ram_bytes: int
    license: str
    license_url: str | None = None
    best_for: str
    available: bool = True
    installed: bool = False


class ModelFit(BaseModel):
    """Why a model was or was not recommended, in the user's terms."""

    model: ModelInfo
    fits_storage: bool
    fits_memory: bool
    is_recommended: bool
    expected_speed: str
    score: float
    reasons: list[str] = []
    blockers: list[str] = []


class StorageBudget(BaseModel):
    drive_id: str
    drive_total_bytes: int
    drive_free_bytes: int
    model_bytes: int
    runtime_bytes: int
    portable_python_bytes: int
    workspace_bytes: int
    reserve_bytes: int
    required_bytes: int
    remaining_bytes: int
    is_sufficient: bool
    message: str


class ModelRecommendations(BaseModel):
    hardware: HardwareProfile
    drive: Drive
    recommended: ModelFit | None = None
    alternative: ModelFit | None = None
    lightweight: ModelFit | None = None
    all_models: list[ModelFit] = []
    catalog_refreshed: bool = False
    catalog_note: str | None = None


class StorageCheckRequest(BaseModel):
    drive_id: str
    model_id: str
    bundle_portable_python: bool = True


# --------------------------------------------------------------------------
# Setup and installation
# --------------------------------------------------------------------------


class UseCase(StrEnum):
    ASSISTANT = "assistant"
    LEARNING = "learning"
    CODING = "coding"
    DOCUMENTS = "documents"
    JOURNALING = "journaling"
    FINANCE = "finance"


class OnboardingProfile(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    use_cases: list[UseCase] = Field(min_length=1)
    experience: str = Field(default="new", max_length=40)
    network_allowed: bool = True
    tone: str = Field(default="balanced", max_length=40)


class InstallRequest(BaseModel):
    drive_id: str
    model_id: str
    profile: OnboardingProfile
    vault_password: str = Field(min_length=12, max_length=1024)
    bundle_portable_python: bool = True
    accept_model_license: bool = False
    #: Set when the user has been told this computer cannot run the engine and
    #: wants the drive prepared for use on a different one anyway.
    build_anyway: bool = False


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class InstallStep(BaseModel):
    key: str
    title: str
    status: StepStatus = StepStatus.PENDING
    detail: str = ""
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    bytes_done: int | None = None
    bytes_total: int | None = None


class JobState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InstallStatus(BaseModel):
    state: JobState
    steps: list[InstallStep] = []
    current_step: str | None = None
    overall_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = ""
    error: str | None = None
    recovery_hint: str | None = None
    install_path: str | None = None
    launcher_path: str | None = None
    can_resume: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None


# --------------------------------------------------------------------------
# Application state
# --------------------------------------------------------------------------


class AppMode(StrEnum):
    SETUP = "setup"
    READY = "ready"


class VaultState(StrEnum):
    ABSENT = "absent"
    LOCKED = "locked"
    UNLOCKED = "unlocked"


class VaultStatus(BaseModel):
    state: VaultState
    secret_count: int = 0
    lock_timeout_seconds: int = 0
    seconds_until_lock: int | None = None


class RuntimeStatus(BaseModel):
    runtime_installed: bool = False
    model_installed: bool = False
    running: bool = False
    model_name: str | None = None
    backend: str | None = None
    gpu_layers: int | None = None
    context_length: int | None = None
    detail: str = ""
    #: Set when this computer will refuse to run the engine at all, so the
    #: interface can say so before the user tries to chat.
    blocked_reason: str | None = None


class InstallationSummary(BaseModel):
    root: str
    drive_id: str
    drive_label: str | None = None
    display_name: str | None = None
    model_name: str | None = None
    created_at: datetime | None = None
    drive_connected: bool = True


class NetworkStatus(BaseModel):
    allowed: bool
    online: bool
    used_for: list[str] = []
    telemetry: bool = False


class AppState(BaseModel):
    mode: AppMode
    version: str
    installation: InstallationSummary | None = None
    candidates: list[InstallationSummary] = []
    vault: VaultStatus
    runtime: RuntimeStatus
    network: NetworkStatus
    onboarding_complete: bool = False
    tutorial_seen: bool = False


class Dashboard(BaseModel):
    display_name: str | None = None
    model_name: str | None = None
    runtime: RuntimeStatus
    vault: VaultStatus
    network: NetworkStatus
    drive_id: str
    storage_used_bytes: int
    storage_total_bytes: int
    pocketmind_bytes: int
    memory_count: int
    document_count: int
    conversation_count: int
    message_count: int


# --------------------------------------------------------------------------
# Chat, memory, documents
# --------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32000)
    conversation_id: int | None = None
    use_memory: bool = True
    use_documents: bool = True


class Conversation(BaseModel):
    id: int
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class Message(BaseModel):
    id: int
    role: str
    content: str
    created_at: str
    sources: list[str] = []


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MemoryCategory(StrEnum):
    PERSONAL = "personal"
    PREFERENCES = "preferences"
    GOALS = "goals"
    PROJECTS = "projects"
    LEARNING = "learning"
    WORK = "work"
    RELATIONSHIPS = "relationships"
    IMPORTANT = "important"
    CUSTOM = "custom"


class MemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    category: str = Field(default=MemoryCategory.PERSONAL, max_length=64)
    importance: int = Field(default=3, ge=1, le=5)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=8000)
    category: str | None = Field(default=None, max_length=64)
    importance: int | None = Field(default=None, ge=1, le=5)


class Memory(BaseModel):
    id: int
    category: str
    content: str
    importance: int
    created_at: str
    updated_at: str


class Document(BaseModel):
    id: int
    filename: str
    source_path: str | None = None
    sha256: str
    byte_size: int
    chunk_count: int
    status: str
    indexed_at: str | None = None
    created_at: str


class FolderImportRequest(BaseModel):
    folder: str = Field(min_length=1)
    recursive: bool = True


# --------------------------------------------------------------------------
# Vault
# --------------------------------------------------------------------------


class VaultPasswordRequest(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


class VaultChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class VaultSecretRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=16000)
    note: str = Field(default="", max_length=2000)


class VaultEntry(BaseModel):
    name: str
    note: str = ""
    created_at: str
    updated_at: str


class VaultSecretValue(BaseModel):
    name: str
    value: str
    note: str = ""


class VaultUnlockResponse(BaseModel):
    session_token: str
    lock_timeout_seconds: int


# --------------------------------------------------------------------------
# Settings, export, backup
# --------------------------------------------------------------------------


class Settings(BaseModel):
    system_prompt: str = Field(default="", max_length=8000)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    context_length: int = Field(default=4096, ge=512, le=131072)
    max_tokens: int = Field(default=1024, ge=64, le=32768)
    stream_responses: bool = True
    memory_enabled: bool = True
    auto_memory: bool = True
    memory_results: int = Field(default=5, ge=0, le=20)
    documents_enabled: bool = True
    chunk_size: int = Field(default=900, ge=200, le=4000)
    chunk_overlap: int = Field(default=150, ge=0, le=1000)
    retrieval_results: int = Field(default=4, ge=0, le=20)
    vault_lock_seconds: int = Field(default=900, ge=60, le=86400)
    network_allowed: bool = True
    allow_model_updates: bool = True
    allow_app_updates: bool = True
    telemetry: bool = False


class ExportRequest(BaseModel):
    include_memories: bool = True
    include_conversations: bool = True
    include_documents: bool = True
    include_vault_names: bool = False
    acknowledge_sensitive: bool = False


class BackupRequest(BaseModel):
    password: str = Field(min_length=12, max_length=1024)
    include_documents: bool = True


class RestoreRequest(BaseModel):
    archive_path: str = Field(min_length=1)
    password: str = Field(min_length=1, max_length=1024)


class KnowledgeSummary(BaseModel):
    """Backing model for the 'what do you know about me?' screen (PRD 73)."""

    display_name: str | None = None
    use_cases: list[str] = []
    memories_by_category: dict[str, list[Memory]] = {}
    documents: list[Document] = []
    conversation_count: int = 0
    vault_entry_count: int = 0
    note: str = ""
