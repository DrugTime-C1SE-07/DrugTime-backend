from datetime import UTC

from sqlalchemy import text

from drugtime.modules.adherence.domain.patient_dose_reminder import ReminderRecord

_FIELDS = """r.id, r.sender_user_id, r.patient_user_id AS patient_id, r.schedule_id,
r.scheduled_at, r.requested_at, r.next_allowed_at, r.status, r.notification_id, n.is_read"""
_SELECT = (
    f"SELECT {_FIELDS} FROM dose_reminder_requests r "
    "JOIN notifications n ON n.id = r.notification_id "
)
_RETAINED = "r.requested_at >= clock_timestamp() - interval '30 days'"


def _record(row):
    return None if row is None else ReminderRecord(**dict(row._mapping))


class SqlPatientDoseReminders:
    def now(self, uow):
        return uow.connection.execute(text("SELECT clock_timestamp()")).scalar_one()

    def lock(self, uow, sender, patient, cmd):
        # Stable namespaces/order. UTC canonical instant makes offset aliases share a lock.
        keys = [
            f"reminder:uuid:{sender}:{cmd.client_uuid}",
            f"reminder:occurrence:{sender}:{patient}:{cmd.schedule_id}:"
            f"{cmd.scheduled_at.astimezone(UTC).isoformat()}",
        ]
        for key in sorted(keys):
            uow.connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key}
            )
        return self.now(uow)

    def by_uuid(self, uow, sender, client_uuid):
        row = uow.connection.execute(
            text(_SELECT + f"WHERE r.sender_user_id = :u AND r.client_uuid = :c AND {_RETAINED}"),
            {"u": sender, "c": client_uuid},
        ).first()
        return _record(row)

    def latest(self, uow, sender, patient, schedule, scheduled_at):
        row = uow.connection.execute(
            text(
                _SELECT
                + f"""
            WHERE r.sender_user_id = :u AND r.patient_user_id = :p
              AND r.schedule_id = :s AND r.scheduled_at = :at AND {_RETAINED}
            ORDER BY r.requested_at DESC, r.id DESC LIMIT 1
        """
            ),
            {"u": sender, "p": patient, "s": schedule, "at": scheduled_at},
        ).first()
        return _record(row)

    def create(self, uow, sender, patient, cmd, now, next_allowed):
        params = {
            "sender": sender,
            "patient": patient,
            "uuid": cmd.client_uuid,
            "schedule": cmd.schedule_id,
            "at": cmd.scheduled_at,
            "now": now,
            "next": next_allowed,
        }
        params["notification"] = uow.connection.execute(
            text("""
            INSERT INTO notifications (user_id, about_patient_user_id, type, content, created_at)
            VALUES (:patient, :patient, 'nhac_uong_thuoc',
                    'Bạn có lời nhắc mới trên DrugTime', :now)
            RETURNING id
        """),
            params,
        ).scalar_one()
        reminder_id = uow.connection.execute(
            text("""
            INSERT INTO dose_reminder_requests
                (sender_user_id, patient_user_id, schedule_id, scheduled_at, client_uuid,
                 notification_id, requested_at, next_allowed_at)
            VALUES (:sender, :patient, :schedule, :at, :uuid, :notification, :now, :next)
            RETURNING id
        """),
            params,
        ).scalar_one()
        uow.connection.execute(
            text("""
            INSERT INTO dose_reminder_outbox (reminder_id, due_at) VALUES (:id, :now)
        """),
            {"id": reminder_id, "now": now},
        )
        return ReminderRecord(
            reminder_id,
            sender,
            patient,
            cmd.schedule_id,
            cmd.scheduled_at,
            now,
            next_allowed,
            "accepted",
            params["notification"],
        )

    def received_metadata(self, uow, user_id, reminder_id=None):
        rows = uow.connection.execute(
            text(f"""
            SELECT r.id, r.sender_user_id FROM dose_reminder_requests r
            WHERE r.patient_user_id = :u AND {_RETAINED} AND r.status <> 'cancelled'
              AND (CAST(:id AS bigint) IS NULL OR r.id = :id)
            ORDER BY r.requested_at DESC, r.id DESC
        """),
            {"u": user_id, "id": reminder_id},
        )
        return [(r.id, r.sender_user_id) for r in rows]

    def received_records(self, uow, user_id, ids):
        if not ids:
            return []
        rows = uow.connection.execute(
            text(
                _SELECT
                + f"""
            WHERE r.patient_user_id = :u AND r.id = ANY(:ids) AND {_RETAINED}
              AND r.status <> 'cancelled' ORDER BY r.requested_at DESC, r.id DESC
        """
            ),
            {"u": user_id, "ids": ids},
        )
        return [_record(row) for row in rows]

    def received_record(self, uow, user_id, reminder_id, is_read=None):
        if is_read is not None:
            uow.connection.execute(
                text(f"""
                UPDATE notifications SET is_read = :read FROM dose_reminder_requests r
                WHERE notifications.id = r.notification_id AND r.id = :id
                  AND r.patient_user_id = :u AND {_RETAINED} AND r.status <> 'cancelled'
            """),
                {"read": is_read, "id": reminder_id, "u": user_id},
            )
        records = self.received_records(uow, user_id, [reminder_id])
        return records[0] if records else None

    def claim(self, uow):
        row = uow.connection.execute(
            text("""
            WITH candidate AS (
                SELECT reminder_id FROM dose_reminder_outbox
                WHERE (state = 'pending' AND due_at <= clock_timestamp())
                   OR (state = 'leased' AND lease_until <= clock_timestamp())
                ORDER BY due_at, reminder_id LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE dose_reminder_outbox o SET state = 'leased',
                lease_until = clock_timestamp() + interval '60 seconds'
            FROM candidate c WHERE o.reminder_id = c.reminder_id
            RETURNING o.reminder_id, o.lease_until
        """)
        ).first()
        return None if row is None else (row.reminder_id, row.lease_until)

    def leased(self, uow, reminder_id, lease):
        # Hold row lock while rechecking/sending. An expired owner never consumes a new lease.
        job = uow.connection.execute(
            text("""
            SELECT attempt_count, delivered_token_hashes FROM dose_reminder_outbox
            WHERE reminder_id = :id AND state = 'leased' AND lease_until = :lease
              AND lease_until > clock_timestamp() FOR UPDATE
        """),
            {"id": reminder_id, "lease": lease},
        ).first()
        if job is None:
            return None
        record = _record(
            uow.connection.execute(text(_SELECT + "WHERE r.id = :id"), {"id": reminder_id}).first()
        )
        return (
            None if record is None else (record, job.attempt_count, set(job.delivered_token_hashes))
        )

    def finish(self, uow, record, *, status, state, attempts, hashes, error=None, delay=0):
        uow.connection.execute(
            text("""
            UPDATE dose_reminder_requests SET status = :status WHERE id = :id
        """),
            {"id": record.id, "status": status},
        )
        uow.connection.execute(
            text("""
            UPDATE dose_reminder_outbox SET state = :state, attempt_count = :attempts,
                delivered_token_hashes = :hashes, lease_until = NULL,
                due_at = clock_timestamp() + make_interval(secs => :delay), last_error_code = :error
            WHERE reminder_id = :id
        """),
            {
                "id": record.id,
                "state": state,
                "attempts": attempts,
                "hashes": sorted(hashes),
                "error": error,
                "delay": delay,
            },
        )

    def cleanup(self, uow, user_id=None):
        # Delete only notifications owned by removed requests, never dose/audit records.
        condition = (
            "requested_at < clock_timestamp() - interval '30 days'"
            if user_id is None
            else "sender_user_id = :u OR patient_user_id = :u"
        )
        suffix = " LIMIT 200" if user_id is None else ""
        rows = uow.connection.execute(
            text(
                "SELECT id, notification_id FROM dose_reminder_requests WHERE ("
                + condition
                + ") ORDER BY id"
                + suffix
                + " FOR UPDATE"
            ),
            {"u": user_id},
        ).all()
        if not rows:
            return 0
        ids, notifications = [r.id for r in rows], [r.notification_id for r in rows]
        uow.connection.execute(
            text("DELETE FROM dose_reminder_outbox WHERE reminder_id = ANY(:ids)"), {"ids": ids}
        )
        uow.connection.execute(
            text("DELETE FROM dose_reminder_requests WHERE id = ANY(:ids)"), {"ids": ids}
        )
        uow.connection.execute(
            text("DELETE FROM notifications WHERE id = ANY(:ids) AND type = 'nhac_uong_thuoc'"),
            {"ids": notifications},
        )
        return len(rows)
