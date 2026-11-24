BEGIN;
-- DeletionCreation.cancel() clears any previously verified OTP challenge so it
-- cannot be replayed to recreate a deletion request after explicit cancellation.
-- RLS policy deletion_otp_api already covers all commands for api_role.
GRANT DELETE ON deletion_otp_challenges TO api_role;
COMMIT;
