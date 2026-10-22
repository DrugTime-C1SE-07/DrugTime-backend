BEGIN;
ALTER TABLE notifications ADD COLUMN medication_name text;
ALTER TABLE notifications ADD COLUMN scheduled_at timestamptz;

-- Legacy rows remain nullable. Only new events must carry their source snapshot.
CREATE FUNCTION require_notification_event_snapshot() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF NEW.medication_name IS NULL OR btrim(NEW.medication_name) = ''
       OR NEW.scheduled_at IS NULL THEN
        RAISE EXCEPTION 'notification event snapshot required' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER notifications_require_snapshot BEFORE INSERT ON notifications
FOR EACH ROW EXECUTE FUNCTION require_notification_event_snapshot();

CREATE INDEX notifications_recipient_patient_idx
    ON notifications (user_id, about_patient_user_id, id);
CREATE INDEX notifications_inbox_order_idx
    ON notifications (user_id, created_at DESC, id DESC);
-- Existing RLS, API UPDATE(is_read), worker INSERT and append-only audit stay intact.
COMMIT;
