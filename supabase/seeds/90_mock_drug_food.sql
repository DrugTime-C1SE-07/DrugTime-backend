-- MOCK DATA FOR LOCAL DEVELOPMENT ONLY (task 4.05, G13). NOT VERIFIED MEDICAL CONTENT.
--
-- Loaded by `supabase db reset` (config.toml [db.seed]); never part of migrations, so
-- `supabase db push` does not send it to a remote database. Task 4.04 must delete or replace
-- this file when real drug-food data lands, otherwise [MOCK] rules reach users.
--
-- Shapes covered (AC19/AC20):
--   [MOCK] Thuốc một hoạt chất nhiều quy tắc -> co_tuong_tac (2 rules, severities 4 and 2)
--   [MOCK] Thuốc phối hợp                   -> co_tuong_tac (one ingredient has a rule)
--   [MOCK] Thuốc không có quy tắc           -> da_kiem_tra_khong_thay
--   [MOCK] Thuốc chưa tách hoạt chất        -> khong_du_du_lieu (no junction rows)
--
-- medications.source is the catalog_source enum, so mock medications keep source/source_ref
-- NULL (never matched by catalog sync soft-delete) and are recognised by the [MOCK] name prefix.

INSERT INTO active_ingredients (standard_name, role, source) VALUES
    ('MOCK Metronidazol', 'dieu_tri_benh_nen', 'MOCK — chưa xác minh, chỉ dùng cho dev'),
    ('MOCK Ibuprofen', 'dieu_tri_benh_nen', 'MOCK — chưa xác minh, chỉ dùng cho dev'),
    ('MOCK Paracetamol', 'dieu_tri_benh_nen', 'MOCK — chưa xác minh, chỉ dùng cho dev');

INSERT INTO medications (name, raw_active_ingredient, strength_text, dosage_form) VALUES
    ('[MOCK] Thuốc một hoạt chất nhiều quy tắc', 'MOCK Metronidazol', '250 mg', 'Viên nén'),
    ('[MOCK] Thuốc phối hợp', 'MOCK Ibuprofen, MOCK Paracetamol', '200 mg + 325 mg', 'Viên nén'),
    ('[MOCK] Thuốc không có quy tắc', 'MOCK Paracetamol', '500 mg', 'Viên nén'),
    ('[MOCK] Thuốc chưa tách hoạt chất', NULL, NULL, 'Viên bao đường');

INSERT INTO medication_active_ingredients (
    medication_id, active_ingredient_id, strength_value, strength_unit, dosing_unit
)
SELECT m.id, a.id, v.strength_value, 'mg', 'vien'
FROM (VALUES
    ('[MOCK] Thuốc một hoạt chất nhiều quy tắc', 'MOCK Metronidazol', 250),
    ('[MOCK] Thuốc phối hợp', 'MOCK Ibuprofen', 200),
    ('[MOCK] Thuốc phối hợp', 'MOCK Paracetamol', 325),
    ('[MOCK] Thuốc không có quy tắc', 'MOCK Paracetamol', 500)
) AS v (medication_name, ingredient_name, strength_value)
JOIN medications m ON m.name = v.medication_name
JOIN active_ingredients a ON a.standard_name = v.ingredient_name;

-- version 1 of each rule; the interaction_rule_set_rule_id trigger fills rule_id.
INSERT INTO drug_food_interactions (
    version, active_ingredient_id, food_to_avoid, severity_level, reason, source,
    verification_status
)
SELECT 1, a.id, v.food, v.severity, v.reason,
       'MOCK — chưa xác minh, chỉ dùng cho dev', 'da_xac_minh'
FROM (VALUES
    ('MOCK Metronidazol', 'Rượu và đồ uống có cồn', 4,
     '[MOCK] Ví dụ để thử giao diện: phản ứng khó chịu khi dùng cùng rượu.'),
    ('MOCK Metronidazol', 'Sữa và chế phẩm từ sữa', 2,
     '[MOCK] Ví dụ để thử giao diện: có thể giảm hấp thu.'),
    ('MOCK Ibuprofen', 'Rượu và đồ uống có cồn', 3,
     '[MOCK] Ví dụ để thử giao diện: tăng nguy cơ kích ứng dạ dày.')
) AS v (ingredient_name, food, severity, reason)
JOIN active_ingredients a ON a.standard_name = v.ingredient_name;
