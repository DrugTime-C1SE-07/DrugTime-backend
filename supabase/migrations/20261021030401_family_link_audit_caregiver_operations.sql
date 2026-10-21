-- Audit for the patient's caregiver management: list caregivers, enable/disable sharing, revoke.
-- Only widens CHECK constraints; existing rows already satisfy the new ones. The table stays
-- append-only (revokes and triggers from 20261015030157 are untouched).
BEGIN;

-- No IF EXISTS: a wrong constraint name must fail the migration, not keep the old rule.
ALTER TABLE public.family_link_audit_events
    DROP CONSTRAINT family_link_audit_events_operation_check,
    DROP CONSTRAINT family_link_audit_events_check2;

ALTER TABLE public.family_link_audit_events
    ADD CONSTRAINT family_link_audit_events_operation_check CHECK (operation IN (
        'list_pending', 'approve', 'reject',
        'list_caregivers', 'enable_sharing', 'disable_sharing', 'revoke'
    )),
    -- Allowed events name their link, except the two list operations.
    ADD CONSTRAINT family_link_audit_events_allowed_link_check CHECK (
        result <> 'allowed' OR operation IN ('list_pending', 'list_caregivers')
        OR link_id IS NOT NULL
    );

COMMIT;
