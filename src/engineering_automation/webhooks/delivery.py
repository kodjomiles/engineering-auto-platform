"""Compatibility export for reliable webhook delivery."""

from engineering_automation.application.use_cases.deliver_webhook import DeliverWebhook

WebhookDispatcher = DeliverWebhook

__all__ = ["WebhookDispatcher"]
