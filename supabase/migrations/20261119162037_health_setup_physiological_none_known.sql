-- Explicit "none" answer for the physiological-state step (pregnancy, breastfeeding) of
-- health setup, separate from conditions_none_known which now covers chronic diseases only.
-- Existing rows get false: their physiological step stays unreported or reported by links.
-- "none_known implies no physiological links" spans user_conditions, so the application
-- enforces it (same as conditions_none_known). Table-level grants already cover the column.
-- IF NOT EXISTS: the hosted dev DB got this column by hand (SQL editor, 2026-11-20), so a
-- later `supabase db push` must still apply this file cleanly and record it.
ALTER TABLE public.health_profile_setup
    ADD COLUMN IF NOT EXISTS physiological_none_known boolean NOT NULL DEFAULT false;
