"""Adapt authenticated engineering events to the routing engine."""

from __future__ import annotations

from engineering_automation.events import (
    DispatchReport,
    EngineeringEvent,
    EventDispatcher,
    EventRouter,
)


class RoutingEventProcessor:
    """Route an event and dispatch its deterministic destination plan."""

    def __init__(self, router: EventRouter, dispatcher: EventDispatcher) -> None:
        self._router = router
        self._dispatcher = dispatcher

    async def process(self, event: EngineeringEvent) -> DispatchReport:
        return await self._dispatcher.dispatch(event, self._router.route(event))
