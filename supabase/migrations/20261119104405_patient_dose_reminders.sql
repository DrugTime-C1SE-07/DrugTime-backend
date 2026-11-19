BEGIN;

CREATE OR REPLACE FUNCTION require_notification_event_snapshot() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF NEW.type <> 'nhac_uong_thuoc' AND
       (NEW.medication_name IS NULL OR btrim(NEW.medication_name) = '' OR NEW.scheduled_at IS NULL) THEN
        RAISE EXCEPTION 'notification event snapshot required' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

COMMIT;
