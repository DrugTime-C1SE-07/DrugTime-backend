import smtplib
import ssl
from email.message import EmailMessage

from drugtime.shared.config import EMAIL_SEND_SLOTS, get_settings
from drugtime.shared.errors import ServiceUnavailable


def send_email_change_otp(email: str, otp: str) -> None:
    settings = get_settings()
    if not settings.deletion_smtp_host or not settings.deletion_smtp_sender:
        raise ServiceUnavailable("service_unavailable")
    if not EMAIL_SEND_SLOTS.acquire(blocking=False):
        raise ServiceUnavailable("service_unavailable")
    try:
        msg = EmailMessage()
        msg["From"] = settings.deletion_smtp_sender
        msg["To"] = email
        msg["Subject"] = "DrugTime – Xác nhận đổi email"
        msg.set_content(f"Mã xác nhận đổi email của bạn là {otp}. Mã có hạn 5 phút.")
        with smtplib.SMTP_SSL(
            settings.deletion_smtp_host,
            settings.deletion_smtp_port,
            timeout=5,
            context=ssl.create_default_context(),
        ) as smtp:
            if settings.deletion_smtp_username:
                smtp.login(settings.deletion_smtp_username, settings.deletion_smtp_password)
            smtp.send_message(msg)
    except (OSError, ValueError, smtplib.SMTPException):
        raise ServiceUnavailable("service_unavailable") from None
    finally:
        EMAIL_SEND_SLOTS.release()
