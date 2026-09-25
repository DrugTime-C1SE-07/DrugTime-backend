"""Giao diện Unit of Work thuần (không phụ thuộc SQLAlchemy).

application/ chỉ biết tới Protocol này; adapters/outbound nhận đối tượng thật
(drugtime.shared.db.SqlUnitOfWork) và dùng .connection để chạy SQL.
"""

from typing import Any, Protocol


class UnitOfWork(Protocol):
    @property
    def connection(self) -> Any: ...
