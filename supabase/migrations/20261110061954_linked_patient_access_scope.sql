BEGIN;

-- Commit before application code can use the new enum value.
ALTER TYPE public.access_data_scope ADD VALUE 'danh_sach_benh_nhan_lien_ket';

COMMIT;
