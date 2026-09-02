from __future__ import annotations

from typing import Optional, Protocol

from src.core.automation_action import ScheduledAutomationAction


class AutomationActionRepository(Protocol):
    def get(self, action_key: str) -> Optional[ScheduledAutomationAction]: ...
    def reserve(self, action: ScheduledAutomationAction) -> bool: ...
    def save(self, action: ScheduledAutomationAction) -> ScheduledAutomationAction: ...
    def list_all(self) -> list[ScheduledAutomationAction]: ...


class InMemoryAutomationActionRepository:
    def __init__(self) -> None:
        self._items: dict[str, ScheduledAutomationAction] = {}

    def get(self, action_key: str) -> Optional[ScheduledAutomationAction]:
        return self._items.get(action_key)

    def reserve(self, action: ScheduledAutomationAction) -> bool:
        if action.action_key in self._items:
            return False
        self._items[action.action_key] = action
        return True

    def save(self, action: ScheduledAutomationAction) -> ScheduledAutomationAction:
        self._items[action.action_key] = action
        return action

    def list_all(self) -> list[ScheduledAutomationAction]:
        return list(self._items.values())
