"""Mã liên kết cố định của mỗi user (QD-04, QD-34)."""

import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

# Chữ hoa và số, bỏ ký tự dễ nhầm 0 O 1 I L (QD-34).
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10
QR_PREFIX = "drugtime://link?code="


@dataclass(frozen=True)
class LinkCode:
    patient_user_id: UUID
    code: str

    @property
    def qr_payload(self) -> str:
        return qr_payload(self.code)


def generate_code(choice: Callable[[Sequence[str]], str] = secrets.choice) -> str:
    return "".join(choice(ALPHABET) for _ in range(CODE_LENGTH))


def qr_payload(code: str) -> str:
    return f"{QR_PREFIX}{code}"
