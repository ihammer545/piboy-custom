from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class LockState(Enum):
    LOCKED = 'locked'
    PULSING = 'pulsing'


class AccessOutcome(Enum):
    GRANTED_NORMAL = 'granted_normal'
    GRANTED_SILENT = 'granted_silent'
    GRANTED_EFFECTS = 'granted_effects'
    DENIED = 'denied'


@dataclass(frozen=True)
class AccessResult:
    outcome: AccessOutcome
    message: str
    scenario: str


@dataclass(frozen=True)
class PulseResult:
    ok: bool
    message: str
    duration_ms: int


class LockPort(ABC):
    """Hardware lock actuator. Pulse only — never hold indefinitely."""

    @abstractmethod
    def get_state(self) -> LockState:
        raise NotImplementedError

    @abstractmethod
    def pulse_unlock(self, duration_ms: int | None = None) -> PulseResult:
        """Start a timed unlock pulse; auto-returns to LOCKED."""
        raise NotImplementedError

    @abstractmethod
    def ensure_safe(self) -> None:
        """Force locked/safe state (startup and recovery)."""
        raise NotImplementedError


class AccessPort(ABC):
    """Validates access codes without exposing secrets to UI/logs."""

    @abstractmethod
    def evaluate_code(self, code: str) -> AccessResult:
        raise NotImplementedError
