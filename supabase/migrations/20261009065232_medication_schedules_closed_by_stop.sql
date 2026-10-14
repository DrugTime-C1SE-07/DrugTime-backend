-- Task 2.04: mark schedules closed by stopping/deleting a medication, so reactivation reopens
-- exactly the schedules that were open at the stop.
ALTER TABLE medication_schedules
ADD COLUMN closed_by_stop_at timestamptz;

-- Existing data: schedules of a stopped medication closed exactly at the stop (2.01 behaviour).
UPDATE medication_schedules ms
SET closed_by_stop_at = um.ended_at
FROM user_medications um
WHERE ms.user_medication_id = um.id
  AND um.ended_at IS NOT NULL
  AND ms.ended_at = um.ended_at
  AND ms.closed_by_stop_at IS NULL;

ALTER TABLE medication_schedules
ADD CONSTRAINT medication_schedules_closed_by_stop_chk
CHECK (closed_by_stop_at IS NULL OR ended_at IS NOT NULL);

COMMENT ON COLUMN medication_schedules.closed_by_stop_at IS
'user_medications.ended_at of the stop/delete that closed this schedule; NULL otherwise. Used to reopen schedules on reactivation.';
