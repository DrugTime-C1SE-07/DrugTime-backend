-- Task 2.16: versioned interaction catalog rules.
-- Each row of active_ingredient_interactions / drug_food_interactions is one immutable version of a
-- rule. A rule keeps a stable rule_id; editing closes the current version (superseded_at) and inserts
-- the next one. Findings shown to patients point at a version id, so their content never changes.

-- ---------------------------------------------------------------- columns and backfill
ALTER TABLE active_ingredient_interactions
    ADD COLUMN rule_id bigint,
    ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN created_by uuid REFERENCES users (id),
    ADD COLUMN superseded_at timestamptz,
    ADD COLUMN deleted_by uuid REFERENCES users (id);

ALTER TABLE drug_food_interactions
    ADD COLUMN rule_id bigint,
    ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN created_by uuid REFERENCES users (id),
    ADD COLUMN superseded_at timestamptz,
    ADD COLUMN deleted_by uuid REFERENCES users (id);

-- Existing rows become version 1 of their own rule.
UPDATE active_ingredient_interactions SET rule_id = id WHERE rule_id IS NULL;
UPDATE drug_food_interactions SET rule_id = id WHERE rule_id IS NULL;

ALTER TABLE active_ingredient_interactions ALTER COLUMN rule_id SET NOT NULL;
ALTER TABLE drug_food_interactions ALTER COLUMN rule_id SET NOT NULL;

-- ---------------------------------------------------------------- constraints
ALTER TABLE active_ingredient_interactions
    ADD CONSTRAINT active_ingredient_interactions_rule_version_uq UNIQUE (rule_id, version),
    ADD CONSTRAINT active_ingredient_interactions_state_chk CHECK (superseded_at IS NULL OR deleted_at IS NULL),
    ADD CONSTRAINT active_ingredient_interactions_deleted_by_chk CHECK (deleted_by IS NULL OR deleted_at IS NOT NULL);

ALTER TABLE drug_food_interactions
    ADD CONSTRAINT drug_food_interactions_rule_version_uq UNIQUE (rule_id, version),
    ADD CONSTRAINT drug_food_interactions_state_chk CHECK (superseded_at IS NULL OR deleted_at IS NULL),
    ADD CONSTRAINT drug_food_interactions_deleted_by_chk CHECK (deleted_by IS NULL OR deleted_at IS NOT NULL);

-- Exactly one version per rule is not superseded (the current one, possibly soft-deleted).
CREATE UNIQUE INDEX active_ingredient_interactions_one_open_version_uq
    ON active_ingredient_interactions (rule_id) WHERE superseded_at IS NULL;
CREATE UNIQUE INDEX drug_food_interactions_one_open_version_uq
    ON drug_food_interactions (rule_id) WHERE superseded_at IS NULL;

-- ---------------------------------------------------------------- indexes over current versions only
DROP INDEX active_ingredient_interactions_a_idx;
DROP INDEX active_ingredient_interactions_b_idx;
DROP INDEX active_ingredient_interactions_pair_uq;
DROP INDEX active_ingredient_interactions_external_uq;
DROP INDEX drug_food_interactions_natural_uq;

CREATE INDEX active_ingredient_interactions_a_idx ON active_ingredient_interactions (ingredient_a_id)
    WHERE deleted_at IS NULL AND superseded_at IS NULL;
CREATE INDEX active_ingredient_interactions_b_idx ON active_ingredient_interactions (ingredient_b_id)
    WHERE deleted_at IS NULL AND superseded_at IS NULL;
CREATE UNIQUE INDEX active_ingredient_interactions_pair_uq ON active_ingredient_interactions
    (LEAST(ingredient_a_id, ingredient_b_id), GREATEST(ingredient_a_id, ingredient_b_id))
    WHERE deleted_at IS NULL AND superseded_at IS NULL AND ingredient_b_id IS NOT NULL;
CREATE UNIQUE INDEX active_ingredient_interactions_external_uq ON active_ingredient_interactions
    (ingredient_a_id, lower(ingredient_b_external_name))
    WHERE deleted_at IS NULL AND superseded_at IS NULL AND ingredient_b_id IS NULL;
CREATE UNIQUE INDEX drug_food_interactions_natural_uq ON drug_food_interactions
    (active_ingredient_id, lower(food_to_avoid))
    WHERE deleted_at IS NULL AND superseded_at IS NULL;

CREATE INDEX drug_food_interactions_ingredient_idx ON drug_food_interactions (active_ingredient_id)
    WHERE deleted_at IS NULL AND superseded_at IS NULL;
CREATE INDEX active_ingredient_interactions_current_order_idx
    ON active_ingredient_interactions (created_at DESC, rule_id DESC)
    WHERE deleted_at IS NULL AND superseded_at IS NULL;
CREATE INDEX drug_food_interactions_current_order_idx
    ON drug_food_interactions (created_at DESC, rule_id DESC)
    WHERE deleted_at IS NULL AND superseded_at IS NULL;

-- ---------------------------------------------------------------- immutability triggers
-- New version: rule_id defaults to its own id (version 1), created_at is the transaction time, and a
-- version is always inserted open.
CREATE FUNCTION interaction_rule_set_rule_id() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF NEW.rule_id IS NULL THEN
        IF NEW.version <> 1 THEN
            RAISE EXCEPTION '%: version % needs an existing rule_id', TG_TABLE_NAME, NEW.version;
        END IF;
        NEW.rule_id := NEW.id;
    END IF;
    IF NEW.superseded_at IS NOT NULL OR NEW.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION '%: a new version must be inserted open', TG_TABLE_NAME;
    END IF;
    NEW.created_at := now();
    RETURN NEW;
END $$;

-- Only allowed update: close an open version once, either superseded_at or deleted_at (+ deleted_by).
CREATE FUNCTION interaction_rule_guard_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF OLD.superseded_at IS NOT NULL OR OLD.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION '%: version % is closed and immutable', TG_TABLE_NAME, OLD.id;
    END IF;
    IF (to_jsonb(NEW) - ARRAY['superseded_at', 'deleted_at', 'deleted_by'])
        IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['superseded_at', 'deleted_at', 'deleted_by']) THEN
        RAISE EXCEPTION '%: version content is immutable', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION interaction_catalog_forbid_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    RAISE EXCEPTION '%: % is not allowed on the versioned interaction catalog', TG_TABLE_NAME, TG_OP;
END $$;

-- Thresholds belong to one version and are written only together with it.
CREATE FUNCTION dose_threshold_guard_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    PERFORM 1
    FROM active_ingredient_interactions i
    WHERE i.id = NEW.interaction_id
      AND i.superseded_at IS NULL
      AND i.deleted_at IS NULL
      AND i.created_at = now();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'dose thresholds can only be added to an open version created in the same transaction';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER active_ingredient_interactions_set_rule_id
    BEFORE INSERT ON active_ingredient_interactions
    FOR EACH ROW EXECUTE FUNCTION interaction_rule_set_rule_id();
CREATE TRIGGER active_ingredient_interactions_guard_update
    BEFORE UPDATE ON active_ingredient_interactions
    FOR EACH ROW EXECUTE FUNCTION interaction_rule_guard_update();
CREATE TRIGGER active_ingredient_interactions_no_delete
    BEFORE DELETE ON active_ingredient_interactions
    FOR EACH ROW EXECUTE FUNCTION interaction_catalog_forbid_mutation();
CREATE TRIGGER active_ingredient_interactions_no_truncate
    BEFORE TRUNCATE ON active_ingredient_interactions
    FOR EACH STATEMENT EXECUTE FUNCTION interaction_catalog_forbid_mutation();

CREATE TRIGGER drug_food_interactions_set_rule_id
    BEFORE INSERT ON drug_food_interactions
    FOR EACH ROW EXECUTE FUNCTION interaction_rule_set_rule_id();
CREATE TRIGGER drug_food_interactions_guard_update
    BEFORE UPDATE ON drug_food_interactions
    FOR EACH ROW EXECUTE FUNCTION interaction_rule_guard_update();
CREATE TRIGGER drug_food_interactions_no_delete
    BEFORE DELETE ON drug_food_interactions
    FOR EACH ROW EXECUTE FUNCTION interaction_catalog_forbid_mutation();
CREATE TRIGGER drug_food_interactions_no_truncate
    BEFORE TRUNCATE ON drug_food_interactions
    FOR EACH STATEMENT EXECUTE FUNCTION interaction_catalog_forbid_mutation();

CREATE TRIGGER dose_thresholds_guard_insert
    BEFORE INSERT ON active_ingredient_interaction_dose_thresholds
    FOR EACH ROW EXECUTE FUNCTION dose_threshold_guard_insert();
CREATE TRIGGER dose_thresholds_no_update_delete
    BEFORE UPDATE OR DELETE ON active_ingredient_interaction_dose_thresholds
    FOR EACH ROW EXECUTE FUNCTION interaction_catalog_forbid_mutation();
CREATE TRIGGER dose_thresholds_no_truncate
    BEFORE TRUNCATE ON active_ingredient_interaction_dose_thresholds
    FOR EACH STATEMENT EXECUTE FUNCTION interaction_catalog_forbid_mutation();

-- ---------------------------------------------------------------- grants (narrowed)
REVOKE ALL ON active_ingredient_interactions, drug_food_interactions, active_ingredient_interaction_dose_thresholds
    FROM api_role, worker_role;

GRANT SELECT, INSERT ON active_ingredient_interactions, drug_food_interactions,
    active_ingredient_interaction_dose_thresholds TO api_role;
GRANT UPDATE (superseded_at, deleted_at, deleted_by) ON active_ingredient_interactions, drug_food_interactions
    TO api_role;
GRANT SELECT ON active_ingredient_interactions, drug_food_interactions,
    active_ingredient_interaction_dose_thresholds TO worker_role;

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON active_ingredient_interactions, drug_food_interactions, '
                'active_ingredient_interaction_dose_thresholds FROM %I', r);
        END IF;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------- documentation
COMMENT ON COLUMN active_ingredient_interactions.rule_id IS
'Stable rule id shared by every version; equals id of version 1.';
COMMENT ON COLUMN active_ingredient_interactions.version IS 'Version number within rule_id, starting at 1.';
COMMENT ON COLUMN active_ingredient_interactions.created_at IS
'When this version was created (transaction time, set by trigger).';
COMMENT ON COLUMN active_ingredient_interactions.created_by IS
'Admin who created this version; NULL for pre-versioning or synchronized data.';
COMMENT ON COLUMN active_ingredient_interactions.superseded_at IS
'When this version was replaced by the next one; content of a version never changes.';
COMMENT ON COLUMN active_ingredient_interactions.deleted_by IS 'Admin who soft-deleted the rule.';
COMMENT ON COLUMN drug_food_interactions.rule_id IS
'Stable rule id shared by every version; equals id of version 1.';
COMMENT ON COLUMN drug_food_interactions.version IS 'Version number within rule_id, starting at 1.';
COMMENT ON COLUMN drug_food_interactions.created_at IS
'When this version was created (transaction time, set by trigger).';
COMMENT ON COLUMN drug_food_interactions.created_by IS
'Admin who created this version; NULL for pre-versioning or synchronized data.';
COMMENT ON COLUMN drug_food_interactions.superseded_at IS
'When this version was replaced by the next one; content of a version never changes.';
COMMENT ON COLUMN drug_food_interactions.deleted_by IS 'Admin who soft-deleted the rule.';
COMMENT ON TABLE active_ingredient_interaction_dose_thresholds IS
'Thresholds of one rule version; inserted only in the transaction that creates the version, never changed.';
