import logging

from drugtime.modules.adherence.api import Alert

log = logging.getLogger(__name__)


class MockGateway:
    def __init__(self) -> None:
        self.sent: list[Alert] = []

    def send(self, alerts: list[Alert]) -> None:
        self.sent.extend(alerts)
        log.info("mock push: %d alert(s)", len(alerts))
