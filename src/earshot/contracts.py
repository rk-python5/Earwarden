"""The five messages that cross Earshot's component boundaries, at version 1.

These are the spec's data contracts as Pydantic models. Every hop validates what it receives, and
whatever fails validation is handed to the screen. Unknown fields fail too, so a newer client
talking to an older daemon hands off rather than being half-understood.

The hook client can't import this module, because it may use only the standard library. Tests
check the JSON it builds against these models instead.

Two changes from the spec's examples:

- `prompt_id` and, on events, `tool_use_id` and `input_sha256` are added. Claude Code 2.1.318
  sends a `prompt_id` with every event, and together they tie a PostToolUse back to the request
  it answers (D-020).
- The audit record's `asr_conf` becomes `recognizer`, because the confidence score was rejected
  (P-05) in favour of two-stage recognition (D-017).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from earshot import wire

# StrictInt, not Literal: Pydantic matches Literal[1] by equality, so JSON `true` would pass as 1.
Version = Annotated[StrictInt, Field(ge=1, le=1)]
Tier = Annotated[StrictInt, Field(ge=0, le=3)]
Source = Literal["claude_code", "python_api"]
Outcome = Literal["allow", "deny", "handoff"]
EventName = Literal["SessionStart", "SessionEnd", "Stop", "Notification", "PostToolUse"]

RequestId = Annotated[str, Field(pattern=r"^req_[0-9A-Za-z]{8,64}$")]
Token = Annotated[str, Field(pattern=r"^[0-9a-f]{32,128}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]
AbsolutePath = Annotated[str, Field(min_length=1, max_length=4096, pattern=r"^/")]

GENESIS_HASH = "0" * 64  # `prev_hash` of the first audit record


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ApprovalRequest(Contract):
    """Hook client to daemon: a tool call that needs permission."""

    v: Version
    id: RequestId
    token: Token
    source: Source
    session_id: ShortText
    prompt_id: ShortText | None = None
    cwd: AbsolutePath
    permission_mode: ShortText
    tool_name: ShortText
    tool_input: dict[str, Any]
    received_at: datetime


class GateScore(Contract):
    """The optional risk gate's view. It can only raise a tier, never lower it."""

    score: float = Field(ge=0, le=1)
    reasons: tuple[ShortText, ...] = ()


class Assessment(Contract):
    """Policy engine to narrator: the tier, the rules that fired, and the fields to speak."""

    v: Version = 1
    tier: Tier
    rules: tuple[ShortText, ...] = ()
    critical: dict[str, Any] = Field(default_factory=dict)
    gate: GateScore | None = None
    voice_ok: bool


class Decision(Contract):
    """Daemon to hook client. Only a deny carries a message, which goes to the agent."""

    v: Version
    id: RequestId
    outcome: Outcome
    message: str | None = Field(default=None, min_length=1, max_length=wire.MAX_DENY_MESSAGE_CHARS)
    tier: Tier | None = None

    @model_validator(mode="after")
    def _message_only_on_deny(self) -> Decision:
        if self.message is not None and self.outcome != "deny":
            raise ValueError("only a deny carries a message")
        return self


class Event(Contract):
    """Hook client to daemon, fire-and-forget: what's happening in a session."""

    v: Version
    token: Token
    source: Source
    event: EventName
    session_id: ShortText
    cwd: AbsolutePath | None = None
    prompt_id: ShortText | None = None
    # SessionStart: how the session started (startup, resume, clear, compact) and its model
    session_source: ShortText | None = None
    model: ShortText | None = None
    # SessionEnd
    reason: ShortText | None = None
    # Stop: what the agent said last, for "finished" announcements
    last_assistant_message: str | None = Field(default=None, max_length=4000)
    # Notification, such as permission_prompt
    notification_type: ShortText | None = None
    message: str | None = Field(default=None, max_length=2000)
    # PostToolUse: the tool ran, so a voice prompt for it is moot (D-020)
    tool_name: ShortText | None = None
    tool_use_id: ShortText | None = None
    input_sha256: Sha256 | None = None
    # PostToolUse of an edit tool: the file it changed, for P-01's session rule
    file_path: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def _post_tool_use_names_its_tool(self) -> Event:
        if self.event == "PostToolUse" and (self.tool_name is None or self.input_sha256 is None):
            raise ValueError("a PostToolUse event needs tool_name and input_sha256")
        return self


class AuditRecord(Contract):
    """One line of the audit log per decision. Its hash covers the previous record's hash."""

    v: Version = 1
    id: RequestId
    ts: datetime
    session: ShortText
    tool: ShortText
    input_sha256: Sha256
    input_redacted: str
    tier: Tier
    rules: tuple[ShortText, ...] = ()
    spoken: str | None = None
    checker: Literal["pass", "fail"] | None = None
    transcript: str | None = None
    recognizer: ShortText | None = None
    challenge: ShortText | None = None
    voiceprint: float | None = None
    gesture: Literal["nod", "shake"] | None = None
    outcome: Literal["allow", "deny", "handoff", "cancelled"]
    reason: ShortText | None = None  # how it ended: decided, tool_ran, hook_closed, timeout...
    timings_ms: dict[str, int] = Field(default_factory=dict)
    prev_hash: Sha256
    hash: Sha256
