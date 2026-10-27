import logging

from drugtime.modules.adherence.api import Alert, SyncRequest

log = logging.getLogger(__name__)


class MockGateway:
    def __init__(self) -> None:
        self.sent: list[Alert] = []
        self.sync_requests: list[SyncRequest] = []

    def send(self, alerts: list[Alert]) -> list[str]:
        self.sent.extend(alerts)
        log.info("mock push: %d alert(s)", len(alerts))
        return []

    def request_sync(self, requests: list[SyncRequest]) -> list[str]:
        self.sync_requests.extend(requests)
        log.info("mock push: %d sync request(s)", len(requests))
        return []
