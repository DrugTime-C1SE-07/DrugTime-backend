-- FILE SINH TỰ ĐỘNG bởi backend/scripts/build_knowledge_seed.py --catalog-out — KHÔNG SỬA TAY.
-- Nguồn: workbook dữ liệu dược
--   (docs/Team1_DTU/03_Design/Database/DrugTime_DuLieuDuoc.xlsx, sheet 11 và 12)
-- workbook sha256: cdc63dbcc3b2763cf589ef07a7e14b494ae37d144c146d7e372b03074279518f
-- Sinh lại: python scripts/build_knowledge_seed.py <workbook> --catalog-out supabase/seeds/20_health_profile_catalog.sql
-- Chỉ chứa dòng 'Trạng thái rà soát' = 'Dược sĩ đã duyệt' (QD-37).
-- Upsert, không xóa dòng: chạy lại an toàn trên DB đã có dữ liệu (db reset và remote).
-- count conditions=4
-- count allergens=15

BEGIN;

-- conditions (khóa tự nhiên: name)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM (VALUES ('benh_tim_mach'), ('dai_thao_duong')) AS v (code)
        WHERE NOT EXISTS (
            SELECT 1 FROM disease_groups g WHERE g.code = v.code
        )
    ) THEN
        RAISE EXCEPTION
            'conditions seed: disease group code missing in disease_groups';
    END IF;
END
$$;
INSERT INTO conditions
    (name, medical_nature, data_role, icd10_code, disease_group_id)
SELECT v.name, v.medical_nature::medical_nature, v.data_role::condition_data_role,
    v.icd10_code::text, g.id
FROM (VALUES
    ('Tăng huyết áp', 'benh_ly', 'sinh_hoat_chat_dieu_tri', 'I10', 'benh_tim_mach'),
    ('Đang cho con bú', 'sinh_ly_binh_thuong', 'dieu_chinh_thuoc_khac', 'Z39.1', NULL),
    ('Đang mang thai', 'sinh_ly_binh_thuong', 'dieu_chinh_thuoc_khac', 'Z33', NULL),
    ('Đái tháo đường type 2', 'benh_ly', 'sinh_hoat_chat_dieu_tri', 'E11', 'dai_thao_duong')
) AS v (name, medical_nature, data_role, icd10_code, group_code)
LEFT JOIN disease_groups g ON g.code = v.group_code::text
ON CONFLICT (name) DO UPDATE SET
    medical_nature = EXCLUDED.medical_nature,
    data_role = EXCLUDED.data_role,
    icd10_code = EXCLUDED.icd10_code,
    disease_group_id = EXCLUDED.disease_group_id;

-- allergens (khóa: id; UNIQUE (category, display_order) hoãn tới COMMIT)
INSERT INTO allergens (id, category, name, display_order, is_active, source) VALUES
    ('penicillin', 'drug', 'Penicillin (Amoxicillin, Ampicillin…)', 1, true, 'Zhou L. và cs., Drug allergies documented in electronic health records of a large healthcare system, Allergy 2016: https://durham-repository.worktribe.com/preview/1408624/19142.pdf'),
    ('cephalosporin', 'drug', 'Cephalosporin (Cefalexin, Ceftriaxon…)', 2, true, 'Bản tin thông tin thuốc BV Bạch Mai số 1/2025 (số liệu Trung tâm DI&ADR Quốc gia): https://apicms.bachmai.gov.vn/documents/0/0/ba-n-tin-tho-ng-tin-thuo-c-so-1-na-m-2025.pdf/61d0beb7-a5eb-4055-b04f-f72737559dee'),
    ('aspirin', 'drug', 'Aspirin', 3, true, 'Zhou L. và cs., Drug allergies documented in electronic health records of a large healthcare system, Allergy 2016: https://durham-repository.worktribe.com/preview/1408624/19142.pdf'),
    ('nsaid', 'drug', 'Thuốc giảm đau chống viêm (NSAID)', 4, true, 'Termedia, Risk factors, clinical presentations and common culprits in drug allergies (Türkiye): https://www.termedia.pl/Risk-factors-clinical-presentations-and-common-culprits-r-nin-drug-allergies-a-case-control-study-from-Turkiye,7,57303,1,0.html'),
    ('iodinated_contrast', 'drug', 'Thuốc cản quang chứa iod', 5, true, 'Tạp chí Y Dược lâm sàng 108 (số liệu Trung tâm DI&ADR Quốc gia 2015–2019): https://tcydls108.benhvien108.vn/index.php/YDLS/article/download/868/1007/'),
    ('quinolone', 'drug', 'Kháng sinh Quinolon', 6, true, 'Tổng quan dị ứng thuốc: https://pmc.ncbi.nlm.nih.gov/articles/PMC12841114'),
    ('seafood', 'food', 'Hải sản (tôm, cua, sò, mực…)', 1, true, 'FDA, Food Allergies: What You Need to Know (9 dị nguyên chính theo FALCPA 2004 và FASTER Act 2021): https://www.fda.gov/food/buy-store-serve-safe-food/food-allergies-what-you-need-know'),
    ('fish', 'food', 'Cá', 2, true, 'FDA, Food Allergies: What You Need to Know (9 dị nguyên chính theo FALCPA 2004 và FASTER Act 2021): https://www.fda.gov/food/buy-store-serve-safe-food/food-allergies-what-you-need-know'),
    ('peanuts', 'food', 'Đậu phộng', 3, true, 'FDA, Food Allergies: What You Need to Know (9 dị nguyên chính theo FALCPA 2004 và FASTER Act 2021): https://www.fda.gov/food/buy-store-serve-safe-food/food-allergies-what-you-need-know'),
    ('tree_nuts', 'food', 'Các loại hạt (điều, óc chó, hạnh nhân…)', 4, true, 'FDA, Food Allergies: What You Need to Know (9 dị nguyên chính theo FALCPA 2004 và FASTER Act 2021): https://www.fda.gov/food/buy-store-serve-safe-food/food-allergies-what-you-need-know'),
    ('eggs', 'food', 'Trứng', 5, true, 'FDA, Food Allergies: What You Need to Know (9 dị nguyên chính theo FALCPA 2004 và FASTER Act 2021): https://www.fda.gov/food/buy-store-serve-safe-food/food-allergies-what-you-need-know'),
    ('milk', 'food', 'Sữa', 6, true, 'FDA, Food Allergies: What You Need to Know (9 dị nguyên chính theo FALCPA 2004 và FASTER Act 2021): https://www.fda.gov/food/buy-store-serve-safe-food/food-allergies-what-you-need-know'),
    ('wheat', 'food', 'Lúa mì', 7, true, 'FDA, Food Allergies: What You Need to Know (9 dị nguyên chính theo FALCPA 2004 và FASTER Act 2021): https://www.fda.gov/food/buy-store-serve-safe-food/food-allergies-what-you-need-know'),
    ('soy', 'food', 'Đậu nành', 8, true, 'FDA, Food Allergies: What You Need to Know (9 dị nguyên chính theo FALCPA 2004 và FASTER Act 2021): https://www.fda.gov/food/buy-store-serve-safe-food/food-allergies-what-you-need-know'),
    ('sesame', 'food', 'Mè (vừng)', 9, true, 'FDA, Food Allergies: What You Need to Know (9 dị nguyên chính theo FALCPA 2004 và FASTER Act 2021): https://www.fda.gov/food/buy-store-serve-safe-food/food-allergies-what-you-need-know')
ON CONFLICT (id) DO UPDATE SET
    category = EXCLUDED.category,
    name = EXCLUDED.name,
    display_order = EXCLUDED.display_order,
    is_active = EXCLUDED.is_active,
    source = EXCLUDED.source;

COMMIT;
