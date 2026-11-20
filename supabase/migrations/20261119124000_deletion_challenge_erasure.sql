BEGIN;
-- DELETE predicates need SELECT on user_id, but worker does not need to read
-- email addresses, digests or challenge material.
GRANT DELETE ON deletion_otp_challenges, email_change_challenges TO worker_role;
GRANT SELECT (user_id) ON deletion_otp_challenges TO worker_role;
GRANT SELECT (user_id) ON email_change_challenges TO worker_role;
CREATE POLICY deletion_otp_worker_lookup ON deletion_otp_challenges
    FOR SELECT TO worker_role USING (true);
CREATE POLICY deletion_otp_worker_erase ON deletion_otp_challenges
    FOR DELETE TO worker_role USING (true);
CREATE POLICY email_change_worker_lookup ON email_change_challenges
    FOR SELECT TO worker_role USING (true);
CREATE POLICY email_change_worker_erase ON email_change_challenges
    FOR DELETE TO worker_role USING (true);
COMMIT;
