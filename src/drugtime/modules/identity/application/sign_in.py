from uuid import UUID

from drugtime.modules.identity.application.ports import AuthProvider, UserRepository
from drugtime.shared.errors import DomainError, Unauthorized


def request_otp(auth: AuthProvider, *, phone: str | None, email: str | None) -> None:
    if (phone is None) == (email is None):
        raise DomainError("Cần đúng một trong hai: phone hoặc email")
    auth.request_otp(phone=phone, email=email)


def verify_otp(
    auth: AuthProvider, users: UserRepository, *, phone: str | None, email: str | None, token: str
) -> dict:
    session = auth.verify_otp(phone=phone, email=email, token=token)
    user_id = UUID(session["user"]["id"])
    user = users.get(user_id)
    if user is None:
        users.create_minimal(user_id, phone=phone, email=email)  # lần đăng nhập đầu tiên
    elif user.erased:
        raise Unauthorized("Tài khoản đã bị xóa")
    return session
