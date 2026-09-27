BEGIN;

DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO public;

CREATE TYPE active_ingredient_role AS ENUM ('dieu_tri_benh_nen', 'trieu_chung_cap_tinh');
CREATE TYPE catalog_source AS ENUM ('dav_drugbank', 'qd_5948', 'duoc_thu_qg');
CREATE TYPE sync_status AS ENUM ('dang_chay', 'thanh_cong', 'that_bai');
CREATE TYPE sync_trigger AS ENUM ('scheduler', 'admin_thu_cong');
CREATE TYPE medical_nature AS ENUM ('benh_ly', 'sinh_ly_binh_thuong');
CREATE TYPE condition_data_role AS ENUM ('sinh_hoat_chat_dieu_tri', 'dieu_chinh_thuoc_khac');
CREATE TYPE yes_no AS ENUM ('co', 'khong');
CREATE TYPE interaction_type AS ENUM ('chong_chi_dinh', 'phu_thuoc_lieu');
CREATE TYPE handling_type AS ENUM ('tranh_phoi_hop', 'can_theo_doi', 'cach_gio', 'giam_lieu');
CREATE TYPE system_role AS ENUM ('user', 'admin');
CREATE TYPE consent_type AS ENUM ('health_data', 'family_sharing', 'ai_meal');
CREATE TYPE consent_status AS ENUM ('dong_y', 'thu_hoi');
CREATE TYPE deletion_status AS ENUM ('cho_duyet', 'da_duyet', 'tu_choi', 'hoan_tat');
CREATE TYPE link_status AS ENUM ('pending', 'active', 'revoked');
CREATE TYPE device_platform AS ENUM ('android', 'ios');
CREATE TYPE access_actor_role AS ENUM ('family', 'admin', 'khong_co_quyen');
CREATE TYPE access_data_scope AS ENUM ('ho_so_suc_khoe', 'danh_sach_thuoc', 'lich_su_tuan_thu', 'canh_bao_tuong_tac', 'goi_y_bua_an');
CREATE TYPE access_result AS ENUM ('allowed', 'denied');
CREATE TYPE dpia_status AS ENUM ('ban_nhap', 'dang_xem_xet', 'da_phe_duyet');
CREATE TYPE prescription_entry_source AS ENUM ('ocr_scan', 'thu_cong', 'mac_dinh');
CREATE TYPE prescription_status AS ENUM ('dang_dung', 'da_ket_thuc');
CREATE TYPE medication_entry_method AS ENUM ('thu_cong', 'ocr_scan');
CREATE TYPE dose_status AS ENUM ('da_uong', 'bo_lo', 'uong_tre');
CREATE TYPE notification_type AS ENUM ('nhac_uong_thuoc', 'canh_bao_bo_lo_lieu_nguoi_than');
CREATE TYPE finding_source_table AS ENUM ('interactions', 'drug_food', 'precautions', 'drug_classes');
CREATE TYPE medication_confirmation AS ENUM ('cho_xac_nhan', 'da_xac_nhan');

CREATE TABLE medications (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    raw_active_ingredient text,
    strength_text text,
    dosage_form text,
    manufacturer_name text,
    manufacturer_country text,
    packaging_spec text,
    source catalog_source,
    source_ref text,
    deleted_at timestamptz,
    CONSTRAINT medications_source_ref_uq UNIQUE (source, source_ref),
    CHECK ((source IS NULL) = (source_ref IS NULL))
);

CREATE TABLE active_ingredients (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    standard_name text NOT NULL UNIQUE,
    role active_ingredient_role NOT NULL,
    pharmacological_group text,
    atc_code text,
    source text
);

CREATE TABLE ingredient_aliases (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    active_ingredient_id bigint NOT NULL REFERENCES active_ingredients (id),
    alias_text text NOT NULL,
    UNIQUE (active_ingredient_id, alias_text)
);

CREATE TABLE disease_groups (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE medication_active_ingredients (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    medication_id bigint NOT NULL REFERENCES medications (id),
    active_ingredient_id bigint NOT NULL REFERENCES active_ingredients (id),
    strength_value numeric NOT NULL CHECK (strength_value > 0),
    strength_unit text NOT NULL,
    dosing_unit text NOT NULL,
    UNIQUE (medication_id, active_ingredient_id)
);

CREATE TABLE active_ingredient_disease_groups (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    active_ingredient_id bigint NOT NULL REFERENCES active_ingredients (id),
    disease_group_id bigint NOT NULL REFERENCES disease_groups (id),
    UNIQUE (active_ingredient_id, disease_group_id)
);

CREATE TABLE catalog_sync_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source catalog_source NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status sync_status NOT NULL DEFAULT 'dang_chay',
    records_inserted integer NOT NULL DEFAULT 0 CHECK (records_inserted >= 0),
    records_updated integer NOT NULL DEFAULT 0 CHECK (records_updated >= 0),
    records_failed integer NOT NULL DEFAULT 0 CHECK (records_failed >= 0),
    error_details jsonb,
    triggered_by sync_trigger NOT NULL,
    CHECK ((status = 'dang_chay') = (finished_at IS NULL)),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE conditions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE,
    medical_nature medical_nature NOT NULL,
    data_role condition_data_role NOT NULL,
    icd10_code text,
    disease_group_id bigint REFERENCES disease_groups (id)
);

CREATE TABLE active_ingredient_interactions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingredient_a_id bigint NOT NULL REFERENCES active_ingredients (id),
    ingredient_b_id bigint REFERENCES active_ingredients (id),
    ingredient_b_external_name text,
    ingredient_b_in_table_a yes_no NOT NULL,
    interaction_type interaction_type NOT NULL,
    severity_level smallint NOT NULL CHECK (severity_level BETWEEN 1 AND 4),
    handling_type handling_type NOT NULL,
    min_interval_hours numeric CHECK (min_interval_hours > 0),
    description text NOT NULL,
    source text NOT NULL,
    verification_status text NOT NULL,
    deleted_at timestamptz,
    CHECK (
        (ingredient_b_in_table_a = 'co' AND ingredient_b_id IS NOT NULL)
        OR (ingredient_b_in_table_a = 'khong' AND ingredient_b_id IS NULL AND ingredient_b_external_name IS NOT NULL)
    ),
    CHECK (ingredient_b_id IS NULL OR ingredient_b_id <> ingredient_a_id)
);

CREATE TABLE active_ingredient_interaction_dose_thresholds (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    interaction_id bigint NOT NULL REFERENCES active_ingredient_interactions (id),
    ingredient_ref char(1) NOT NULL CHECK (ingredient_ref IN ('A', 'B')),
    min_dose numeric CHECK (min_dose >= 0),
    max_dose numeric CHECK (max_dose >= 0),
    dose_unit text NOT NULL,
    severity_level smallint NOT NULL CHECK (severity_level BETWEEN 1 AND 4),
    warning_text text NOT NULL,
    CHECK (min_dose IS NOT NULL OR max_dose IS NOT NULL),
    CHECK (min_dose IS NULL OR max_dose IS NULL OR min_dose <= max_dose)
);

CREATE TABLE drug_food_interactions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    active_ingredient_id bigint NOT NULL REFERENCES active_ingredients (id),
    food_to_avoid text NOT NULL,
    severity_level smallint NOT NULL CHECK (severity_level BETWEEN 1 AND 4),
    reason text NOT NULL,
    source text NOT NULL,
    verification_status text NOT NULL,
    deleted_at timestamptz
);

CREATE TABLE active_ingredient_precautions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    active_ingredient_id bigint NOT NULL REFERENCES active_ingredients (id),
    condition_id bigint NOT NULL REFERENCES conditions (id),
    severity_level smallint NOT NULL CHECK (severity_level BETWEEN 1 AND 4),
    adjustment_description text NOT NULL,
    source text NOT NULL,
    verification_status text NOT NULL,
    deleted_at timestamptz
);

CREATE TABLE drug_classes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    class_name text NOT NULL UNIQUE,
    source text
);

CREATE TABLE active_ingredient_drug_classes (
    active_ingredient_id bigint NOT NULL REFERENCES active_ingredients (id),
    drug_class_id bigint NOT NULL REFERENCES drug_classes (id),
    PRIMARY KEY (active_ingredient_id, drug_class_id)
);

CREATE TABLE users (
    id uuid PRIMARY KEY,
    full_name text,
    date_of_birth date,
    gender text,
    phone_number text UNIQUE CHECK (phone_number ~ '^\+[1-9][0-9]{7,14}$'),
    email text,
    system_role system_role NOT NULL DEFAULT 'user',
    erased_at timestamptz,
    CHECK (erased_at IS NOT NULL OR email IS NOT NULL OR phone_number IS NOT NULL),
    CHECK (erased_at IS NULL OR (full_name IS NULL AND date_of_birth IS NULL AND gender IS NULL AND email IS NULL AND phone_number IS NULL))
);

CREATE UNIQUE INDEX users_email_lower_uq ON users (lower(email));

CREATE TABLE user_consents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    consent_type consent_type NOT NULL,
    status consent_status NOT NULL DEFAULT 'dong_y',
    consented_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    document_version text NOT NULL,
    CHECK ((status = 'thu_hoi') = (revoked_at IS NOT NULL)),
    CHECK (revoked_at IS NULL OR revoked_at >= consented_at)
);

CREATE UNIQUE INDEX user_consents_one_active_idx ON user_consents (user_id, consent_type) WHERE status = 'dong_y';

CREATE TABLE data_deletion_requests (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    status deletion_status NOT NULL DEFAULT 'cho_duyet',
    requested_at timestamptz NOT NULL DEFAULT now(),
    handled_by_admin_id uuid REFERENCES users (id),
    handled_at timestamptz,
    rejection_reason text,
    completed_at timestamptz,
    last_error text,
    CHECK (status <> 'tu_choi' OR rejection_reason IS NOT NULL),
    CHECK ((status = 'hoan_tat') = (completed_at IS NOT NULL)),
    CHECK (status = 'tu_choi' OR rejection_reason IS NULL),
    CHECK (status = 'cho_duyet' OR (handled_by_admin_id IS NOT NULL AND handled_at IS NOT NULL)),
    CHECK (handled_by_admin_id IS NULL OR handled_by_admin_id <> user_id)
);

CREATE UNIQUE INDEX data_deletion_requests_one_open_idx ON data_deletion_requests (user_id) WHERE status IN ('cho_duyet', 'da_duyet');
CREATE INDEX data_deletion_requests_status_idx ON data_deletion_requests (status, requested_at);

CREATE TABLE caregiver_links (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_user_id uuid NOT NULL REFERENCES users (id),
    family_user_id uuid NOT NULL REFERENCES users (id),
    status link_status NOT NULL DEFAULT 'pending',
    sharing_enabled boolean NOT NULL DEFAULT false,
    linked_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    UNIQUE (patient_user_id, family_user_id),
    CHECK (patient_user_id <> family_user_id),
    CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
);

CREATE INDEX caregiver_links_family_idx ON caregiver_links (family_user_id, status);
CREATE INDEX caregiver_links_patient_idx ON caregiver_links (patient_user_id, status);

CREATE TABLE link_codes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_user_id uuid NOT NULL REFERENCES users (id),
    code text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    is_used boolean NOT NULL DEFAULT false,
    family_user_id uuid REFERENCES users (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (family_user_id IS NULL OR is_used),
    CHECK (family_user_id IS NULL OR family_user_id <> patient_user_id),
    CHECK (expires_at > created_at)
);

CREATE INDEX link_codes_patient_idx ON link_codes (patient_user_id);
CREATE INDEX link_codes_family_idx ON link_codes (family_user_id);

CREATE TABLE device_tokens (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    fcm_token text NOT NULL UNIQUE,
    platform device_platform NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX device_tokens_user_idx ON device_tokens (user_id);

CREATE TABLE access_logs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id uuid NOT NULL REFERENCES users (id),
    actor_role access_actor_role NOT NULL,
    patient_user_id uuid NOT NULL REFERENCES users (id),
    data_scope access_data_scope NOT NULL,
    result access_result NOT NULL,
    rejection_reason text,
    accessed_at timestamptz NOT NULL DEFAULT now(),
    CHECK (result = 'denied' OR actor_role IN ('family', 'admin')),
    CHECK (actor_user_id <> patient_user_id)
);

CREATE INDEX access_logs_patient_idx ON access_logs (patient_user_id, accessed_at);
CREATE INDEX access_logs_actor_idx ON access_logs (actor_user_id, accessed_at);

CREATE TABLE dpia_records (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    data_flow_name text NOT NULL,
    has_cross_border_transfer boolean NOT NULL,
    status dpia_status NOT NULL DEFAULT 'ban_nhap',
    approved_by_id uuid REFERENCES users (id),
    approval_date date,
    CHECK ((status = 'da_phe_duyet') = (approved_by_id IS NOT NULL AND approval_date IS NOT NULL))
);

CREATE TABLE user_conditions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    condition_id bigint NOT NULL REFERENCES conditions (id),
    subtype text,
    stage text,
    UNIQUE (user_id, condition_id)
);

CREATE TABLE prescriptions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    entry_source prescription_entry_source NOT NULL,
    prescribed_date date,
    prescribing_facility text,
    status prescription_status NOT NULL DEFAULT 'dang_dung',
    UNIQUE (id, user_id)
);

CREATE INDEX prescriptions_user_idx ON prescriptions (user_id, status);

CREATE TABLE user_medications (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    prescription_id bigint NOT NULL,
    medication_id bigint NOT NULL REFERENCES medications (id),
    entry_method medication_entry_method NOT NULL,
    confirmation_status medication_confirmation NOT NULL DEFAULT 'cho_xac_nhan',
    quantity_per_dose numeric NOT NULL CHECK (quantity_per_dose > 0),
    doses_per_day smallint NOT NULL CHECK (doses_per_day > 0),
    has_interaction_data boolean NOT NULL DEFAULT false,
    ended_at timestamptz,
    FOREIGN KEY (prescription_id, user_id) REFERENCES prescriptions (id, user_id)
);

CREATE INDEX user_medications_user_idx ON user_medications (user_id);
CREATE INDEX user_medications_prescription_idx ON user_medications (prescription_id);
CREATE INDEX user_medications_medication_idx ON user_medications (medication_id);

CREATE TABLE medication_schedules (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_medication_id bigint NOT NULL REFERENCES user_medications (id),
    intake_time time NOT NULL,
    days_of_week smallint[] NOT NULL CHECK (cardinality(days_of_week) > 0 AND days_of_week <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]),
    reminder_enabled boolean NOT NULL DEFAULT true,
    effective_from timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    CHECK (ended_at IS NULL OR ended_at >= effective_from)
);

CREATE INDEX medication_schedules_user_medication_idx ON medication_schedules (user_medication_id);
CREATE INDEX medication_schedules_open_idx ON medication_schedules (intake_time) WHERE ended_at IS NULL;

CREATE TABLE dose_logs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    medication_schedule_id bigint NOT NULL REFERENCES medication_schedules (id),
    scheduled_at timestamptz NOT NULL,
    taken_at timestamptz,
    status dose_status NOT NULL,
    client_uuid uuid UNIQUE,
    synced_at timestamptz,
    UNIQUE (medication_schedule_id, scheduled_at),
    CHECK ((status = 'bo_lo' AND taken_at IS NULL) OR (status IN ('da_uong', 'uong_tre') AND taken_at IS NOT NULL))
);

CREATE TABLE notifications (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    about_patient_user_id uuid NOT NULL REFERENCES users (id),
    type notification_type NOT NULL,
    content text NOT NULL,
    is_read boolean NOT NULL DEFAULT false,
    dedupe_key text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX notifications_inbox_idx ON notifications (user_id, is_read, created_at DESC);
CREATE INDEX notifications_about_patient_idx ON notifications (about_patient_user_id);

CREATE TABLE meal_suggestions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    suggestion_content jsonb NOT NULL,
    based_on_condition bigint REFERENCES conditions (id),
    served_from_cache boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX meal_suggestions_user_idx ON meal_suggestions (user_id, created_at DESC);

CREATE TABLE regimen_analysis_snapshots (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    analyzed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX regimen_analysis_snapshots_user_idx ON regimen_analysis_snapshots (user_id, analyzed_at DESC);

CREATE TABLE regimen_analysis_findings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id bigint NOT NULL REFERENCES regimen_analysis_snapshots (id),
    warning_type text NOT NULL,
    source_table finding_source_table NOT NULL,
    source_id bigint NOT NULL,
    is_shown_to_user boolean NOT NULL DEFAULT true
);

CREATE INDEX regimen_analysis_findings_snapshot_idx ON regimen_analysis_findings (snapshot_id);

CREATE TABLE regimen_analysis_finding_medications (
    finding_id bigint NOT NULL REFERENCES regimen_analysis_findings (id),
    user_medication_id bigint NOT NULL REFERENCES user_medications (id),
    PRIMARY KEY (finding_id, user_medication_id)
);

CREATE INDEX regimen_analysis_finding_medications_user_medication_idx ON regimen_analysis_finding_medications (user_medication_id);

CREATE TABLE user_recommendations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    finding_id bigint NOT NULL REFERENCES regimen_analysis_findings (id),
    is_viewed boolean NOT NULL DEFAULT false,
    is_handled boolean NOT NULL DEFAULT false,
    UNIQUE (user_id, finding_id)
);

CREATE INDEX user_recommendations_finding_idx ON user_recommendations (finding_id);

CREATE TABLE sample_patient_scenarios (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scenario_name text NOT NULL UNIQUE,
    expected_result jsonb NOT NULL,
    pharmacist_assessment text
);

CREATE TABLE scenario_conditions (
    scenario_id bigint NOT NULL REFERENCES sample_patient_scenarios (id),
    condition_id bigint NOT NULL REFERENCES conditions (id),
    PRIMARY KEY (scenario_id, condition_id)
);

CREATE TABLE scenario_active_ingredients (
    scenario_id bigint NOT NULL REFERENCES sample_patient_scenarios (id),
    active_ingredient_id bigint NOT NULL REFERENCES active_ingredients (id),
    PRIMARY KEY (scenario_id, active_ingredient_id)
);

CREATE TABLE missed_dose_scan_cursor (
    job_name text PRIMARY KEY,
    scanned_until timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE worker_heartbeats (
    worker_name text PRIMARY KEY,
    last_beat_at timestamptz NOT NULL DEFAULT now(),
    instance_id text NOT NULL
);

CREATE INDEX medications_active_name_idx ON medications (name) WHERE deleted_at IS NULL;
CREATE INDEX ingredient_aliases_text_idx ON ingredient_aliases (lower(alias_text));
CREATE INDEX medication_active_ingredients_ingredient_idx ON medication_active_ingredients (active_ingredient_id);
CREATE INDEX active_ingredient_disease_groups_group_idx ON active_ingredient_disease_groups (disease_group_id);
CREATE INDEX catalog_sync_runs_history_idx ON catalog_sync_runs (source, started_at DESC);
CREATE UNIQUE INDEX catalog_sync_runs_one_running_idx ON catalog_sync_runs (source) WHERE status = 'dang_chay';
CREATE INDEX active_ingredient_interactions_a_idx ON active_ingredient_interactions (ingredient_a_id) WHERE deleted_at IS NULL;
CREATE INDEX active_ingredient_interactions_b_idx ON active_ingredient_interactions (ingredient_b_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX active_ingredient_interactions_pair_uq ON active_ingredient_interactions (LEAST(ingredient_a_id, ingredient_b_id), GREATEST(ingredient_a_id, ingredient_b_id)) WHERE deleted_at IS NULL AND ingredient_b_id IS NOT NULL;
CREATE UNIQUE INDEX active_ingredient_interactions_external_uq ON active_ingredient_interactions (ingredient_a_id, lower(ingredient_b_external_name)) WHERE deleted_at IS NULL AND ingredient_b_id IS NULL;
CREATE INDEX dose_thresholds_interaction_idx ON active_ingredient_interaction_dose_thresholds (interaction_id);
CREATE UNIQUE INDEX drug_food_interactions_natural_uq ON drug_food_interactions (active_ingredient_id, lower(food_to_avoid)) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX active_ingredient_precautions_natural_uq ON active_ingredient_precautions (active_ingredient_id, condition_id) WHERE deleted_at IS NULL;
CREATE INDEX active_ingredient_precautions_condition_idx ON active_ingredient_precautions (condition_id) WHERE deleted_at IS NULL;
CREATE INDEX active_ingredient_drug_classes_class_idx ON active_ingredient_drug_classes (drug_class_id);
CREATE INDEX user_consents_user_idx ON user_consents (user_id, consent_type);
CREATE INDEX conditions_disease_group_idx ON conditions (disease_group_id);
CREATE INDEX user_medications_open_idx ON user_medications (user_id) WHERE ended_at IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api_role') THEN
        CREATE ROLE api_role LOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'worker_role') THEN
        CREATE ROLE worker_role LOGIN NOINHERIT;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO api_role, worker_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO api_role, worker_role;

GRANT SELECT, INSERT, UPDATE ON medications, drug_food_interactions, active_ingredient_interactions, active_ingredient_precautions TO api_role, worker_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON active_ingredients, ingredient_aliases, medication_active_ingredients, active_ingredient_disease_groups, disease_groups, conditions, drug_classes, active_ingredient_drug_classes, active_ingredient_interaction_dose_thresholds TO api_role, worker_role;

GRANT SELECT ON catalog_sync_runs TO api_role;
GRANT SELECT, INSERT, UPDATE ON catalog_sync_runs TO worker_role;

GRANT SELECT, INSERT, UPDATE ON users TO api_role;
GRANT SELECT, UPDATE ON users TO worker_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON device_tokens TO api_role;
GRANT SELECT, DELETE ON device_tokens TO worker_role;

GRANT SELECT, INSERT, UPDATE ON user_consents TO api_role;
GRANT SELECT ON user_consents TO worker_role;

GRANT SELECT, INSERT, UPDATE ON data_deletion_requests TO api_role;
GRANT SELECT, UPDATE ON data_deletion_requests TO worker_role;

GRANT SELECT, INSERT, UPDATE ON dpia_records TO api_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON caregiver_links, link_codes TO api_role;
GRANT SELECT, UPDATE, DELETE ON caregiver_links, link_codes TO worker_role;

GRANT SELECT, INSERT ON access_logs TO api_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON user_conditions, prescriptions, user_medications, medication_schedules TO api_role;
GRANT SELECT, DELETE ON user_conditions, prescriptions, user_medications, medication_schedules TO worker_role;

GRANT SELECT, INSERT, UPDATE ON dose_logs TO api_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON dose_logs TO worker_role;

GRANT SELECT ON notifications TO api_role;
GRANT UPDATE (is_read) ON notifications TO api_role;
GRANT SELECT, INSERT, DELETE ON notifications TO worker_role;

GRANT SELECT, INSERT ON meal_suggestions TO api_role;
GRANT SELECT, DELETE ON meal_suggestions TO worker_role;

GRANT SELECT, INSERT, UPDATE ON regimen_analysis_snapshots, regimen_analysis_findings, regimen_analysis_finding_medications, user_recommendations TO api_role;
GRANT SELECT, DELETE ON regimen_analysis_snapshots, regimen_analysis_findings, regimen_analysis_finding_medications, user_recommendations TO worker_role;

GRANT SELECT, INSERT, UPDATE ON missed_dose_scan_cursor TO worker_role;

GRANT SELECT ON worker_heartbeats TO api_role;
GRANT SELECT, INSERT, UPDATE ON worker_heartbeats TO worker_role;

DO $$
DECLARE
    t text;
    r text;
BEGIN
    FOR t IN
        SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        FOREACH r IN ARRAY ARRAY['api_role', 'worker_role']
        LOOP
            IF has_table_privilege(r, format('public.%I', t), 'SELECT') THEN
                EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO %I USING (true) WITH CHECK (true)', t || '_' || r, t, r);
            END IF;
        END LOOP;
    END LOOP;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM authenticated;
    END IF;
END
$$;
COMMIT;