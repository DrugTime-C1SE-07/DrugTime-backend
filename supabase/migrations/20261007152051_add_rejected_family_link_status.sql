ALTER TYPE link_status ADD VALUE IF NOT EXISTS 'rejected';

ALTER TABLE caregiver_links
ADD COLUMN rejected_at timestamptz;

ALTER TABLE caregiver_links
ADD CONSTRAINT caregiver_links_rejected_at_status_check
CHECK ((status::text = 'rejected') = (rejected_at IS NOT NULL));

ALTER TABLE caregiver_links
ADD CONSTRAINT caregiver_links_single_terminal_timestamp_check
CHECK (NOT (revoked_at IS NOT NULL AND rejected_at IS NOT NULL));
