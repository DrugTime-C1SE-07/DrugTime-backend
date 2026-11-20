-- Display-only pill shape and colour a patient picks for each medication (S07-M2b,
-- adhoc-20261120-add-medication-ux). Values mirror the PillShape / PillColor enums of
-- api_contract/openapi.json, so no mapping layer is needed. text + CHECK instead of a
-- PostgreSQL enum: new values only need the constraint replaced.
-- Nullable without default: existing rows stay NULL ("not chosen") and the ALTER only
-- touches the catalog, not the table data. Table-level grants already cover the columns;
-- RLS is unchanged.
ALTER TABLE public.user_medications
    ADD COLUMN pill_shape text,
    ADD COLUMN pill_color text,
    ADD CONSTRAINT user_medications_pill_shape_chk CHECK (
        pill_shape IS NULL OR pill_shape IN (
            'capsule', 'round_tablet', 'oblong_tablet', 'softgel', 'effervescent',
            'powder_sachet', 'syrup', 'drops', 'spray', 'injection_pen', 'topical'
        )
    ),
    ADD CONSTRAINT user_medications_pill_color_chk CHECK (
        pill_color IS NULL OR pill_color IN (
            'white', 'yellow', 'orange', 'pink', 'red', 'brown', 'blue', 'green', 'purple',
            'gray'
        )
    );
