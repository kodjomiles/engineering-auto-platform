"""Pure recipient preference policy."""

from engineering_automation.domain.notifications import (
    ContactPoint,
    Notification,
    RecipientPreferences,
)


def suppression_reason(
    notification: Notification,
    recipient: RecipientPreferences,
    contact_point: ContactPoint,
) -> str | None:
    """Explain why one contact point should not receive a notification."""

    if notification.priority < recipient.minimum_priority:
        return "notification priority is below recipient minimum"
    if notification.topic in recipient.muted_topics:
        return "notification topic is muted"
    if not contact_point.enabled:
        return "contact point is disabled"
    return None
