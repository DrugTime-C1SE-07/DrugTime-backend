create sequence "public"."active_ingredient_interaction_dose_thresholds_id_seq";

create sequence "public"."active_ingredient_interactions_id_seq";

create sequence "public"."active_ingredient_nhom_benh_id_seq";

create sequence "public"."active_ingredient_precautions_id_seq";

create sequence "public"."active_ingredients_id_seq";

create sequence "public"."caregiver_links_id_seq";

create sequence "public"."conditions_id_seq";

create sequence "public"."don_thuoc_id_seq";

create sequence "public"."dose_logs_id_seq";

create sequence "public"."drug_classes_id_seq";

create sequence "public"."drug_food_interactions_id_seq";

create sequence "public"."ingredient_aliases_id_seq";

create sequence "public"."kich_ban_benh_nhan_mau_id_seq";

create sequence "public"."meal_suggestions_id_seq";

create sequence "public"."medication_active_ingredients_id_seq";

create sequence "public"."medication_schedules_id_seq";

create sequence "public"."medications_id_seq";

create sequence "public"."notifications_id_seq";

create sequence "public"."regimen_analysis_findings_id_seq";

create sequence "public"."regimen_analysis_snapshots_id_seq";

create sequence "public"."user_conditions_id_seq";

create sequence "public"."user_consents_id_seq";

create sequence "public"."user_medications_id_seq";

create sequence "public"."user_recommendations_id_seq";

create sequence "public"."users_id_seq";


  create table "public"."active_ingredient_drug_classes" (
    "active_ingredient_id" bigint not null,
    "drug_class_id" bigint not null
      );



  create table "public"."active_ingredient_interaction_dose_thresholds" (
    "id" bigint not null default nextval('public.active_ingredient_interaction_dose_thresholds_id_seq'::regclass),
    "interaction_id" bigint not null,
    "ingredient_ref" text not null,
    "lieu_toi_thieu" numeric,
    "lieu_toi_da" numeric,
    "don_vi_lieu" text,
    "muc_do" smallint,
    "canh_bao_text" text
      );



  create table "public"."active_ingredient_interactions" (
    "id" bigint not null default nextval('public.active_ingredient_interactions_id_seq'::regclass),
    "hoat_chat_a_id" bigint not null,
    "hoat_chat_b_id" bigint,
    "hoat_chat_b_ten_ngoai" text,
    "hoat_chat_b_trong_bang_a" text not null,
    "loai_tuong_tac" text not null,
    "muc_do" smallint not null,
    "loai_xu_ly" text not null,
    "khoang_cach_toi_thieu_gio" numeric,
    "mo_ta" text,
    "nguon" text,
    "trang_thai_xac_minh" text not null default 'cho_duoc_si_xac_minh'::text
      );



  create table "public"."active_ingredient_nhom_benh" (
    "id" bigint not null default nextval('public.active_ingredient_nhom_benh_id_seq'::regclass),
    "active_ingredient_id" bigint not null,
    "nhom_benh" text not null
      );



  create table "public"."active_ingredient_precautions" (
    "id" bigint not null default nextval('public.active_ingredient_precautions_id_seq'::regclass),
    "hoat_chat_id" bigint not null,
    "dieu_kien_id" bigint not null,
    "muc_do" text not null,
    "mo_ta_dieu_chinh" text,
    "nguon" text,
    "trang_thai_xac_minh" text not null default 'cho_duoc_si_xac_minh'::text
      );



  create table "public"."active_ingredients" (
    "id" bigint not null default nextval('public.active_ingredients_id_seq'::regclass),
    "ten_hoat_chat_chuan" text not null,
    "vai_tro" text not null,
    "nhom_benh" bigint,
    "nhom_duoc_ly" text,
    "atc_code" text,
    "nguon" text
      );



  create table "public"."caregiver_links" (
    "id" bigint not null default nextval('public.caregiver_links_id_seq'::regclass),
    "patient_user_id" bigint not null,
    "family_user_id" bigint not null,
    "trang_thai" text
      );



  create table "public"."conditions" (
    "id" bigint not null default nextval('public.conditions_id_seq'::regclass),
    "ten" text not null,
    "ban_chat_y_khoa" text not null,
    "vai_tro_du_lieu" text not null,
    "icd10_code" text
      );



  create table "public"."don_thuoc" (
    "id" bigint not null default nextval('public.don_thuoc_id_seq'::regclass),
    "user_id" bigint not null,
    "nguon_nhap" text not null,
    "ngay_ke_don" date,
    "noi_ke_don" text,
    "trang_thai" text not null default 'dang_dung'::text
      );



  create table "public"."dose_logs" (
    "id" bigint not null default nextval('public.dose_logs_id_seq'::regclass),
    "medication_schedule_id" bigint not null,
    "thoi_gian_du_kien" timestamp with time zone,
    "thoi_gian_thuc_uong" timestamp with time zone,
    "trang_thai" text
      );



  create table "public"."drug_classes" (
    "id" bigint not null default nextval('public.drug_classes_id_seq'::regclass),
    "ten_nhom" text not null,
    "nguon" text
      );



  create table "public"."drug_food_interactions" (
    "id" bigint not null default nextval('public.drug_food_interactions_id_seq'::regclass),
    "hoat_chat_id" bigint not null,
    "thuc_pham_can_tranh" text not null,
    "muc_do" smallint,
    "ly_do" text,
    "nguon" text,
    "trang_thai_xac_minh" text not null default 'cho_duoc_si_xac_minh'::text
      );



  create table "public"."ingredient_aliases" (
    "id" bigint not null default nextval('public.ingredient_aliases_id_seq'::regclass),
    "active_ingredient_id" bigint not null,
    "alias_text" text not null
      );



  create table "public"."kich_ban_benh_nhan_mau" (
    "id" bigint not null default nextval('public.kich_ban_benh_nhan_mau_id_seq'::regclass),
    "ten_kich_ban" text not null,
    "ket_qua_ky_vong" text,
    "danh_gia_duoc_si" text
      );



  create table "public"."kich_ban_dieu_kien" (
    "kich_ban_id" bigint not null,
    "dieu_kien_id" bigint not null
      );



  create table "public"."kich_ban_hoat_chat" (
    "kich_ban_id" bigint not null,
    "hoat_chat_id" bigint not null
      );



  create table "public"."meal_suggestions" (
    "id" bigint not null default nextval('public.meal_suggestions_id_seq'::regclass),
    "user_id" bigint not null,
    "noi_dung_goi_y" text,
    "dua_tren_dieu_kien" bigint
      );



  create table "public"."medication_active_ingredients" (
    "id" bigint not null default nextval('public.medication_active_ingredients_id_seq'::regclass),
    "medication_id" bigint not null,
    "active_ingredient_id" bigint not null,
    "ham_luong_value" numeric,
    "ham_luong_unit" text,
    "don_vi_dinh_luong" text
      );



  create table "public"."medication_schedules" (
    "id" bigint not null default nextval('public.medication_schedules_id_seq'::regclass),
    "user_medication_id" bigint not null,
    "gio_uong" time without time zone,
    "ngay_trong_tuan" text,
    "bat_tat_nhac" boolean not null default true
      );



  create table "public"."medications" (
    "id" bigint not null default nextval('public.medications_id_seq'::regclass),
    "ten_thuoc" text,
    "hoat_chat_raw" text,
    "ham_luong" text,
    "dang_bao_che" text,
    "cty_san_xuat_ten" text,
    "cty_san_xuat_nuoc" text,
    "quy_cach_dong_goi" text
      );



  create table "public"."notifications" (
    "id" bigint not null default nextval('public.notifications_id_seq'::regclass),
    "user_id" bigint not null,
    "loai" text,
    "noi_dung" text,
    "da_doc" boolean not null default false
      );



  create table "public"."regimen_analysis_finding_don_thuoc" (
    "finding_id" bigint not null,
    "don_thuoc_id" bigint not null
      );



  create table "public"."regimen_analysis_findings" (
    "id" bigint not null default nextval('public.regimen_analysis_findings_id_seq'::regclass),
    "snapshot_id" bigint not null,
    "loai_canh_bao" text,
    "nguon_du_lieu" text,
    "hien_thi_cho_nguoi_dung" text
      );



  create table "public"."regimen_analysis_snapshots" (
    "id" bigint not null default nextval('public.regimen_analysis_snapshots_id_seq'::regclass),
    "user_id" bigint not null,
    "thoi_gian_phan_tich" timestamp with time zone not null default now()
      );



  create table "public"."user_conditions" (
    "id" bigint not null default nextval('public.user_conditions_id_seq'::regclass),
    "user_id" bigint not null,
    "condition_id" bigint not null,
    "subtype" text,
    "phan_do" text
      );



  create table "public"."user_consents" (
    "id" bigint not null default nextval('public.user_consents_id_seq'::regclass),
    "user_id" bigint not null,
    "loai_dong_y" text not null,
    "trang_thai" boolean not null default false,
    "thoi_gian_dong_y" timestamp with time zone
      );



  create table "public"."user_medications" (
    "id" bigint not null default nextval('public.user_medications_id_seq'::regclass),
    "user_id" bigint not null,
    "don_thuoc_id" bigint not null,
    "medication_id" bigint,
    "cach_nhap" text not null,
    "trang_thai_xac_nhan" text,
    "so_luong_moi_lan" numeric,
    "so_lan_moi_ngay" numeric,
    "co_du_lieu_tuong_tac" boolean not null default false
      );



  create table "public"."user_recommendations" (
    "id" bigint not null default nextval('public.user_recommendations_id_seq'::regclass),
    "user_id" bigint not null,
    "finding_id" bigint not null,
    "da_xem" boolean not null default false,
    "da_xu_ly" boolean not null default false
      );



  create table "public"."users" (
    "id" bigint not null default nextval('public.users_id_seq'::regclass),
    "ho_ten" text,
    "ngay_sinh" date,
    "gioi_tinh" text,
    "so_dien_thoai" text,
    "che_do_nguoi_cao_tuoi" boolean default false,
    "vai_tro" text not null
      );


alter sequence "public"."active_ingredient_interaction_dose_thresholds_id_seq" owned by "public"."active_ingredient_interaction_dose_thresholds"."id";

alter sequence "public"."active_ingredient_interactions_id_seq" owned by "public"."active_ingredient_interactions"."id";

alter sequence "public"."active_ingredient_nhom_benh_id_seq" owned by "public"."active_ingredient_nhom_benh"."id";

alter sequence "public"."active_ingredient_precautions_id_seq" owned by "public"."active_ingredient_precautions"."id";

alter sequence "public"."active_ingredients_id_seq" owned by "public"."active_ingredients"."id";

alter sequence "public"."caregiver_links_id_seq" owned by "public"."caregiver_links"."id";

alter sequence "public"."conditions_id_seq" owned by "public"."conditions"."id";

alter sequence "public"."don_thuoc_id_seq" owned by "public"."don_thuoc"."id";

alter sequence "public"."dose_logs_id_seq" owned by "public"."dose_logs"."id";

alter sequence "public"."drug_classes_id_seq" owned by "public"."drug_classes"."id";

alter sequence "public"."drug_food_interactions_id_seq" owned by "public"."drug_food_interactions"."id";

alter sequence "public"."ingredient_aliases_id_seq" owned by "public"."ingredient_aliases"."id";

alter sequence "public"."kich_ban_benh_nhan_mau_id_seq" owned by "public"."kich_ban_benh_nhan_mau"."id";

alter sequence "public"."meal_suggestions_id_seq" owned by "public"."meal_suggestions"."id";

alter sequence "public"."medication_active_ingredients_id_seq" owned by "public"."medication_active_ingredients"."id";

alter sequence "public"."medication_schedules_id_seq" owned by "public"."medication_schedules"."id";

alter sequence "public"."medications_id_seq" owned by "public"."medications"."id";

alter sequence "public"."notifications_id_seq" owned by "public"."notifications"."id";

alter sequence "public"."regimen_analysis_findings_id_seq" owned by "public"."regimen_analysis_findings"."id";

alter sequence "public"."regimen_analysis_snapshots_id_seq" owned by "public"."regimen_analysis_snapshots"."id";

alter sequence "public"."user_conditions_id_seq" owned by "public"."user_conditions"."id";

alter sequence "public"."user_consents_id_seq" owned by "public"."user_consents"."id";

alter sequence "public"."user_medications_id_seq" owned by "public"."user_medications"."id";

alter sequence "public"."user_recommendations_id_seq" owned by "public"."user_recommendations"."id";

alter sequence "public"."users_id_seq" owned by "public"."users"."id";

CREATE UNIQUE INDEX active_ingredient_drug_classes_pkey ON public.active_ingredient_drug_classes USING btree (active_ingredient_id, drug_class_id);

CREATE UNIQUE INDEX active_ingredient_interaction_dose_thresholds_pkey ON public.active_ingredient_interaction_dose_thresholds USING btree (id);

CREATE UNIQUE INDEX active_ingredient_interactions_pkey ON public.active_ingredient_interactions USING btree (id);

CREATE UNIQUE INDEX active_ingredient_nhom_benh_pkey ON public.active_ingredient_nhom_benh USING btree (id);

CREATE UNIQUE INDEX active_ingredient_precautions_pkey ON public.active_ingredient_precautions USING btree (id);

CREATE UNIQUE INDEX active_ingredients_pkey ON public.active_ingredients USING btree (id);

CREATE UNIQUE INDEX caregiver_links_pkey ON public.caregiver_links USING btree (id);

CREATE UNIQUE INDEX conditions_pkey ON public.conditions USING btree (id);

CREATE UNIQUE INDEX don_thuoc_pkey ON public.don_thuoc USING btree (id);

CREATE UNIQUE INDEX dose_logs_pkey ON public.dose_logs USING btree (id);

CREATE UNIQUE INDEX drug_classes_pkey ON public.drug_classes USING btree (id);

CREATE UNIQUE INDEX drug_food_interactions_pkey ON public.drug_food_interactions USING btree (id);

CREATE UNIQUE INDEX ingredient_aliases_pkey ON public.ingredient_aliases USING btree (id);

CREATE UNIQUE INDEX kich_ban_benh_nhan_mau_pkey ON public.kich_ban_benh_nhan_mau USING btree (id);

CREATE UNIQUE INDEX kich_ban_dieu_kien_pkey ON public.kich_ban_dieu_kien USING btree (kich_ban_id, dieu_kien_id);

CREATE UNIQUE INDEX kich_ban_hoat_chat_pkey ON public.kich_ban_hoat_chat USING btree (kich_ban_id, hoat_chat_id);

CREATE UNIQUE INDEX meal_suggestions_pkey ON public.meal_suggestions USING btree (id);

CREATE UNIQUE INDEX medication_active_ingredients_pkey ON public.medication_active_ingredients USING btree (id);

CREATE UNIQUE INDEX medication_schedules_pkey ON public.medication_schedules USING btree (id);

CREATE UNIQUE INDEX medications_pkey ON public.medications USING btree (id);

CREATE UNIQUE INDEX notifications_pkey ON public.notifications USING btree (id);

CREATE UNIQUE INDEX regimen_analysis_finding_don_thuoc_pkey ON public.regimen_analysis_finding_don_thuoc USING btree (finding_id, don_thuoc_id);

CREATE UNIQUE INDEX regimen_analysis_findings_pkey ON public.regimen_analysis_findings USING btree (id);

CREATE UNIQUE INDEX regimen_analysis_snapshots_pkey ON public.regimen_analysis_snapshots USING btree (id);

CREATE UNIQUE INDEX user_conditions_pkey ON public.user_conditions USING btree (id);

CREATE UNIQUE INDEX user_consents_pkey ON public.user_consents USING btree (id);

CREATE UNIQUE INDEX user_medications_pkey ON public.user_medications USING btree (id);

CREATE UNIQUE INDEX user_recommendations_pkey ON public.user_recommendations USING btree (id);

CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id);

alter table "public"."active_ingredient_drug_classes" add constraint "active_ingredient_drug_classes_pkey" PRIMARY KEY using index "active_ingredient_drug_classes_pkey";

alter table "public"."active_ingredient_interaction_dose_thresholds" add constraint "active_ingredient_interaction_dose_thresholds_pkey" PRIMARY KEY using index "active_ingredient_interaction_dose_thresholds_pkey";

alter table "public"."active_ingredient_interactions" add constraint "active_ingredient_interactions_pkey" PRIMARY KEY using index "active_ingredient_interactions_pkey";

alter table "public"."active_ingredient_nhom_benh" add constraint "active_ingredient_nhom_benh_pkey" PRIMARY KEY using index "active_ingredient_nhom_benh_pkey";

alter table "public"."active_ingredient_precautions" add constraint "active_ingredient_precautions_pkey" PRIMARY KEY using index "active_ingredient_precautions_pkey";

alter table "public"."active_ingredients" add constraint "active_ingredients_pkey" PRIMARY KEY using index "active_ingredients_pkey";

alter table "public"."caregiver_links" add constraint "caregiver_links_pkey" PRIMARY KEY using index "caregiver_links_pkey";

alter table "public"."conditions" add constraint "conditions_pkey" PRIMARY KEY using index "conditions_pkey";

alter table "public"."don_thuoc" add constraint "don_thuoc_pkey" PRIMARY KEY using index "don_thuoc_pkey";

alter table "public"."dose_logs" add constraint "dose_logs_pkey" PRIMARY KEY using index "dose_logs_pkey";

alter table "public"."drug_classes" add constraint "drug_classes_pkey" PRIMARY KEY using index "drug_classes_pkey";

alter table "public"."drug_food_interactions" add constraint "drug_food_interactions_pkey" PRIMARY KEY using index "drug_food_interactions_pkey";

alter table "public"."ingredient_aliases" add constraint "ingredient_aliases_pkey" PRIMARY KEY using index "ingredient_aliases_pkey";

alter table "public"."kich_ban_benh_nhan_mau" add constraint "kich_ban_benh_nhan_mau_pkey" PRIMARY KEY using index "kich_ban_benh_nhan_mau_pkey";

alter table "public"."kich_ban_dieu_kien" add constraint "kich_ban_dieu_kien_pkey" PRIMARY KEY using index "kich_ban_dieu_kien_pkey";

alter table "public"."kich_ban_hoat_chat" add constraint "kich_ban_hoat_chat_pkey" PRIMARY KEY using index "kich_ban_hoat_chat_pkey";

alter table "public"."meal_suggestions" add constraint "meal_suggestions_pkey" PRIMARY KEY using index "meal_suggestions_pkey";

alter table "public"."medication_active_ingredients" add constraint "medication_active_ingredients_pkey" PRIMARY KEY using index "medication_active_ingredients_pkey";

alter table "public"."medication_schedules" add constraint "medication_schedules_pkey" PRIMARY KEY using index "medication_schedules_pkey";

alter table "public"."medications" add constraint "medications_pkey" PRIMARY KEY using index "medications_pkey";

alter table "public"."notifications" add constraint "notifications_pkey" PRIMARY KEY using index "notifications_pkey";

alter table "public"."regimen_analysis_finding_don_thuoc" add constraint "regimen_analysis_finding_don_thuoc_pkey" PRIMARY KEY using index "regimen_analysis_finding_don_thuoc_pkey";

alter table "public"."regimen_analysis_findings" add constraint "regimen_analysis_findings_pkey" PRIMARY KEY using index "regimen_analysis_findings_pkey";

alter table "public"."regimen_analysis_snapshots" add constraint "regimen_analysis_snapshots_pkey" PRIMARY KEY using index "regimen_analysis_snapshots_pkey";

alter table "public"."user_conditions" add constraint "user_conditions_pkey" PRIMARY KEY using index "user_conditions_pkey";

alter table "public"."user_consents" add constraint "user_consents_pkey" PRIMARY KEY using index "user_consents_pkey";

alter table "public"."user_medications" add constraint "user_medications_pkey" PRIMARY KEY using index "user_medications_pkey";

alter table "public"."user_recommendations" add constraint "user_recommendations_pkey" PRIMARY KEY using index "user_recommendations_pkey";

alter table "public"."users" add constraint "users_pkey" PRIMARY KEY using index "users_pkey";

alter table "public"."active_ingredient_drug_classes" add constraint "active_ingredient_drug_classes_active_ingredient_id_fkey" FOREIGN KEY (active_ingredient_id) REFERENCES public.active_ingredients(id) not valid;

alter table "public"."active_ingredient_drug_classes" validate constraint "active_ingredient_drug_classes_active_ingredient_id_fkey";

alter table "public"."active_ingredient_drug_classes" add constraint "active_ingredient_drug_classes_drug_class_id_fkey" FOREIGN KEY (drug_class_id) REFERENCES public.drug_classes(id) not valid;

alter table "public"."active_ingredient_drug_classes" validate constraint "active_ingredient_drug_classes_drug_class_id_fkey";

alter table "public"."active_ingredient_interaction_dose_thresholds" add constraint "active_ingredient_interaction_dose_thresho_ingredient_ref_check" CHECK ((ingredient_ref = ANY (ARRAY['A'::text, 'B'::text]))) not valid;

alter table "public"."active_ingredient_interaction_dose_thresholds" validate constraint "active_ingredient_interaction_dose_thresho_ingredient_ref_check";

alter table "public"."active_ingredient_interaction_dose_thresholds" add constraint "active_ingredient_interaction_dose_threshol_interaction_id_fkey" FOREIGN KEY (interaction_id) REFERENCES public.active_ingredient_interactions(id) not valid;

alter table "public"."active_ingredient_interaction_dose_thresholds" validate constraint "active_ingredient_interaction_dose_threshol_interaction_id_fkey";

alter table "public"."active_ingredient_interaction_dose_thresholds" add constraint "active_ingredient_interaction_dose_thresholds_muc_do_check" CHECK (((muc_do >= 1) AND (muc_do <= 4))) not valid;

alter table "public"."active_ingredient_interaction_dose_thresholds" validate constraint "active_ingredient_interaction_dose_thresholds_muc_do_check";

alter table "public"."active_ingredient_interactions" add constraint "active_ingredient_interactions_hoat_chat_a_id_fkey" FOREIGN KEY (hoat_chat_a_id) REFERENCES public.active_ingredients(id) not valid;

alter table "public"."active_ingredient_interactions" validate constraint "active_ingredient_interactions_hoat_chat_a_id_fkey";

alter table "public"."active_ingredient_interactions" add constraint "active_ingredient_interactions_hoat_chat_b_id_fkey" FOREIGN KEY (hoat_chat_b_id) REFERENCES public.active_ingredients(id) not valid;

alter table "public"."active_ingredient_interactions" validate constraint "active_ingredient_interactions_hoat_chat_b_id_fkey";

alter table "public"."active_ingredient_interactions" add constraint "active_ingredient_interactions_hoat_chat_b_trong_bang_a_check" CHECK ((hoat_chat_b_trong_bang_a = ANY (ARRAY['co'::text, 'khong'::text]))) not valid;

alter table "public"."active_ingredient_interactions" validate constraint "active_ingredient_interactions_hoat_chat_b_trong_bang_a_check";

alter table "public"."active_ingredient_interactions" add constraint "active_ingredient_interactions_loai_tuong_tac_check" CHECK ((loai_tuong_tac = ANY (ARRAY['chong_chi_dinh'::text, 'phu_thuoc_lieu'::text]))) not valid;

alter table "public"."active_ingredient_interactions" validate constraint "active_ingredient_interactions_loai_tuong_tac_check";

alter table "public"."active_ingredient_interactions" add constraint "active_ingredient_interactions_loai_xu_ly_check" CHECK ((loai_xu_ly = ANY (ARRAY['tranh_phoi_hop'::text, 'can_theo_doi'::text, 'cach_gio'::text, 'giam_lieu'::text]))) not valid;

alter table "public"."active_ingredient_interactions" validate constraint "active_ingredient_interactions_loai_xu_ly_check";

alter table "public"."active_ingredient_interactions" add constraint "active_ingredient_interactions_muc_do_check" CHECK (((muc_do >= 1) AND (muc_do <= 4))) not valid;

alter table "public"."active_ingredient_interactions" validate constraint "active_ingredient_interactions_muc_do_check";

alter table "public"."active_ingredient_nhom_benh" add constraint "active_ingredient_nhom_benh_active_ingredient_id_fkey" FOREIGN KEY (active_ingredient_id) REFERENCES public.active_ingredients(id) not valid;

alter table "public"."active_ingredient_nhom_benh" validate constraint "active_ingredient_nhom_benh_active_ingredient_id_fkey";

alter table "public"."active_ingredient_precautions" add constraint "active_ingredient_precautions_dieu_kien_id_fkey" FOREIGN KEY (dieu_kien_id) REFERENCES public.conditions(id) not valid;

alter table "public"."active_ingredient_precautions" validate constraint "active_ingredient_precautions_dieu_kien_id_fkey";

alter table "public"."active_ingredient_precautions" add constraint "active_ingredient_precautions_hoat_chat_id_fkey" FOREIGN KEY (hoat_chat_id) REFERENCES public.active_ingredients(id) not valid;

alter table "public"."active_ingredient_precautions" validate constraint "active_ingredient_precautions_hoat_chat_id_fkey";

alter table "public"."active_ingredients" add constraint "active_ingredients_vai_tro_check" CHECK ((vai_tro = ANY (ARRAY['dieu_tri_benh_nen'::text, 'trieu_chung_cap_tinh'::text]))) not valid;

alter table "public"."active_ingredients" validate constraint "active_ingredients_vai_tro_check";

alter table "public"."caregiver_links" add constraint "caregiver_links_family_user_id_fkey" FOREIGN KEY (family_user_id) REFERENCES public.users(id) not valid;

alter table "public"."caregiver_links" validate constraint "caregiver_links_family_user_id_fkey";

alter table "public"."caregiver_links" add constraint "caregiver_links_patient_user_id_fkey" FOREIGN KEY (patient_user_id) REFERENCES public.users(id) not valid;

alter table "public"."caregiver_links" validate constraint "caregiver_links_patient_user_id_fkey";

alter table "public"."conditions" add constraint "conditions_ban_chat_y_khoa_check" CHECK ((ban_chat_y_khoa = ANY (ARRAY['benh_ly'::text, 'sinh_ly_binh_thuong'::text]))) not valid;

alter table "public"."conditions" validate constraint "conditions_ban_chat_y_khoa_check";

alter table "public"."conditions" add constraint "conditions_vai_tro_du_lieu_check" CHECK ((vai_tro_du_lieu = ANY (ARRAY['sinh_hoat_chat_dieu_tri'::text, 'dieu_chinh_thuoc_khac'::text]))) not valid;

alter table "public"."conditions" validate constraint "conditions_vai_tro_du_lieu_check";

alter table "public"."don_thuoc" add constraint "don_thuoc_nguon_nhap_check" CHECK ((nguon_nhap = ANY (ARRAY['ocr_scan'::text, 'thu_cong'::text, 'mac_dinh'::text]))) not valid;

alter table "public"."don_thuoc" validate constraint "don_thuoc_nguon_nhap_check";

alter table "public"."don_thuoc" add constraint "don_thuoc_trang_thai_check" CHECK ((trang_thai = ANY (ARRAY['dang_dung'::text, 'da_ket_thuc'::text]))) not valid;

alter table "public"."don_thuoc" validate constraint "don_thuoc_trang_thai_check";

alter table "public"."don_thuoc" add constraint "don_thuoc_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public.users(id) not valid;

alter table "public"."don_thuoc" validate constraint "don_thuoc_user_id_fkey";

alter table "public"."dose_logs" add constraint "dose_logs_medication_schedule_id_fkey" FOREIGN KEY (medication_schedule_id) REFERENCES public.medication_schedules(id) not valid;

alter table "public"."dose_logs" validate constraint "dose_logs_medication_schedule_id_fkey";

alter table "public"."dose_logs" add constraint "dose_logs_trang_thai_check" CHECK ((trang_thai = ANY (ARRAY['Đã uống'::text, 'Bỏ lỡ'::text, 'Uống trễ'::text]))) not valid;

alter table "public"."dose_logs" validate constraint "dose_logs_trang_thai_check";

alter table "public"."drug_food_interactions" add constraint "drug_food_interactions_hoat_chat_id_fkey" FOREIGN KEY (hoat_chat_id) REFERENCES public.active_ingredients(id) not valid;

alter table "public"."drug_food_interactions" validate constraint "drug_food_interactions_hoat_chat_id_fkey";

alter table "public"."drug_food_interactions" add constraint "drug_food_interactions_muc_do_check" CHECK (((muc_do >= 1) AND (muc_do <= 4))) not valid;

alter table "public"."drug_food_interactions" validate constraint "drug_food_interactions_muc_do_check";

alter table "public"."ingredient_aliases" add constraint "ingredient_aliases_active_ingredient_id_fkey" FOREIGN KEY (active_ingredient_id) REFERENCES public.active_ingredients(id) not valid;

alter table "public"."ingredient_aliases" validate constraint "ingredient_aliases_active_ingredient_id_fkey";

alter table "public"."kich_ban_dieu_kien" add constraint "kich_ban_dieu_kien_dieu_kien_id_fkey" FOREIGN KEY (dieu_kien_id) REFERENCES public.conditions(id) not valid;

alter table "public"."kich_ban_dieu_kien" validate constraint "kich_ban_dieu_kien_dieu_kien_id_fkey";

alter table "public"."kich_ban_dieu_kien" add constraint "kich_ban_dieu_kien_kich_ban_id_fkey" FOREIGN KEY (kich_ban_id) REFERENCES public.kich_ban_benh_nhan_mau(id) not valid;

alter table "public"."kich_ban_dieu_kien" validate constraint "kich_ban_dieu_kien_kich_ban_id_fkey";

alter table "public"."kich_ban_hoat_chat" add constraint "kich_ban_hoat_chat_hoat_chat_id_fkey" FOREIGN KEY (hoat_chat_id) REFERENCES public.active_ingredients(id) not valid;

alter table "public"."kich_ban_hoat_chat" validate constraint "kich_ban_hoat_chat_hoat_chat_id_fkey";

alter table "public"."kich_ban_hoat_chat" add constraint "kich_ban_hoat_chat_kich_ban_id_fkey" FOREIGN KEY (kich_ban_id) REFERENCES public.kich_ban_benh_nhan_mau(id) not valid;

alter table "public"."kich_ban_hoat_chat" validate constraint "kich_ban_hoat_chat_kich_ban_id_fkey";

alter table "public"."meal_suggestions" add constraint "meal_suggestions_dua_tren_dieu_kien_fkey" FOREIGN KEY (dua_tren_dieu_kien) REFERENCES public.conditions(id) not valid;

alter table "public"."meal_suggestions" validate constraint "meal_suggestions_dua_tren_dieu_kien_fkey";

alter table "public"."meal_suggestions" add constraint "meal_suggestions_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public.users(id) not valid;

alter table "public"."meal_suggestions" validate constraint "meal_suggestions_user_id_fkey";

alter table "public"."medication_active_ingredients" add constraint "medication_active_ingredients_active_ingredient_id_fkey" FOREIGN KEY (active_ingredient_id) REFERENCES public.active_ingredients(id) not valid;

alter table "public"."medication_active_ingredients" validate constraint "medication_active_ingredients_active_ingredient_id_fkey";

alter table "public"."medication_active_ingredients" add constraint "medication_active_ingredients_medication_id_fkey" FOREIGN KEY (medication_id) REFERENCES public.medications(id) not valid;

alter table "public"."medication_active_ingredients" validate constraint "medication_active_ingredients_medication_id_fkey";

alter table "public"."medication_schedules" add constraint "medication_schedules_user_medication_id_fkey" FOREIGN KEY (user_medication_id) REFERENCES public.user_medications(id) not valid;

alter table "public"."medication_schedules" validate constraint "medication_schedules_user_medication_id_fkey";

alter table "public"."notifications" add constraint "notifications_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public.users(id) not valid;

alter table "public"."notifications" validate constraint "notifications_user_id_fkey";

alter table "public"."regimen_analysis_finding_don_thuoc" add constraint "regimen_analysis_finding_don_thuoc_don_thuoc_id_fkey" FOREIGN KEY (don_thuoc_id) REFERENCES public.don_thuoc(id) not valid;

alter table "public"."regimen_analysis_finding_don_thuoc" validate constraint "regimen_analysis_finding_don_thuoc_don_thuoc_id_fkey";

alter table "public"."regimen_analysis_finding_don_thuoc" add constraint "regimen_analysis_finding_don_thuoc_finding_id_fkey" FOREIGN KEY (finding_id) REFERENCES public.regimen_analysis_findings(id) not valid;

alter table "public"."regimen_analysis_finding_don_thuoc" validate constraint "regimen_analysis_finding_don_thuoc_finding_id_fkey";

alter table "public"."regimen_analysis_findings" add constraint "regimen_analysis_findings_snapshot_id_fkey" FOREIGN KEY (snapshot_id) REFERENCES public.regimen_analysis_snapshots(id) not valid;

alter table "public"."regimen_analysis_findings" validate constraint "regimen_analysis_findings_snapshot_id_fkey";

alter table "public"."regimen_analysis_snapshots" add constraint "regimen_analysis_snapshots_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public.users(id) not valid;

alter table "public"."regimen_analysis_snapshots" validate constraint "regimen_analysis_snapshots_user_id_fkey";

alter table "public"."user_conditions" add constraint "user_conditions_condition_id_fkey" FOREIGN KEY (condition_id) REFERENCES public.conditions(id) not valid;

alter table "public"."user_conditions" validate constraint "user_conditions_condition_id_fkey";

alter table "public"."user_conditions" add constraint "user_conditions_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public.users(id) not valid;

alter table "public"."user_conditions" validate constraint "user_conditions_user_id_fkey";

alter table "public"."user_consents" add constraint "user_consents_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public.users(id) not valid;

alter table "public"."user_consents" validate constraint "user_consents_user_id_fkey";

alter table "public"."user_medications" add constraint "user_medications_cach_nhap_check" CHECK ((cach_nhap = ANY (ARRAY['thu_cong'::text, 'ocr_scan'::text]))) not valid;

alter table "public"."user_medications" validate constraint "user_medications_cach_nhap_check";

alter table "public"."user_medications" add constraint "user_medications_don_thuoc_id_fkey" FOREIGN KEY (don_thuoc_id) REFERENCES public.don_thuoc(id) not valid;

alter table "public"."user_medications" validate constraint "user_medications_don_thuoc_id_fkey";

alter table "public"."user_medications" add constraint "user_medications_medication_id_fkey" FOREIGN KEY (medication_id) REFERENCES public.medications(id) not valid;

alter table "public"."user_medications" validate constraint "user_medications_medication_id_fkey";

alter table "public"."user_medications" add constraint "user_medications_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public.users(id) not valid;

alter table "public"."user_medications" validate constraint "user_medications_user_id_fkey";

alter table "public"."user_recommendations" add constraint "user_recommendations_finding_id_fkey" FOREIGN KEY (finding_id) REFERENCES public.regimen_analysis_findings(id) not valid;

alter table "public"."user_recommendations" validate constraint "user_recommendations_finding_id_fkey";

alter table "public"."user_recommendations" add constraint "user_recommendations_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public.users(id) not valid;

alter table "public"."user_recommendations" validate constraint "user_recommendations_user_id_fkey";

alter table "public"."users" add constraint "users_vai_tro_check" CHECK ((vai_tro = ANY (ARRAY['Patient'::text, 'Family Member'::text]))) not valid;

alter table "public"."users" validate constraint "users_vai_tro_check";

grant delete on table "public"."active_ingredient_drug_classes" to "anon";

grant insert on table "public"."active_ingredient_drug_classes" to "anon";

grant references on table "public"."active_ingredient_drug_classes" to "anon";

grant select on table "public"."active_ingredient_drug_classes" to "anon";

grant trigger on table "public"."active_ingredient_drug_classes" to "anon";

grant truncate on table "public"."active_ingredient_drug_classes" to "anon";

grant update on table "public"."active_ingredient_drug_classes" to "anon";

grant delete on table "public"."active_ingredient_drug_classes" to "authenticated";

grant insert on table "public"."active_ingredient_drug_classes" to "authenticated";

grant references on table "public"."active_ingredient_drug_classes" to "authenticated";

grant select on table "public"."active_ingredient_drug_classes" to "authenticated";

grant trigger on table "public"."active_ingredient_drug_classes" to "authenticated";

grant truncate on table "public"."active_ingredient_drug_classes" to "authenticated";

grant update on table "public"."active_ingredient_drug_classes" to "authenticated";

grant delete on table "public"."active_ingredient_drug_classes" to "service_role";

grant insert on table "public"."active_ingredient_drug_classes" to "service_role";

grant references on table "public"."active_ingredient_drug_classes" to "service_role";

grant select on table "public"."active_ingredient_drug_classes" to "service_role";

grant trigger on table "public"."active_ingredient_drug_classes" to "service_role";

grant truncate on table "public"."active_ingredient_drug_classes" to "service_role";

grant update on table "public"."active_ingredient_drug_classes" to "service_role";

grant delete on table "public"."active_ingredient_interaction_dose_thresholds" to "anon";

grant insert on table "public"."active_ingredient_interaction_dose_thresholds" to "anon";

grant references on table "public"."active_ingredient_interaction_dose_thresholds" to "anon";

grant select on table "public"."active_ingredient_interaction_dose_thresholds" to "anon";

grant trigger on table "public"."active_ingredient_interaction_dose_thresholds" to "anon";

grant truncate on table "public"."active_ingredient_interaction_dose_thresholds" to "anon";

grant update on table "public"."active_ingredient_interaction_dose_thresholds" to "anon";

grant delete on table "public"."active_ingredient_interaction_dose_thresholds" to "authenticated";

grant insert on table "public"."active_ingredient_interaction_dose_thresholds" to "authenticated";

grant references on table "public"."active_ingredient_interaction_dose_thresholds" to "authenticated";

grant select on table "public"."active_ingredient_interaction_dose_thresholds" to "authenticated";

grant trigger on table "public"."active_ingredient_interaction_dose_thresholds" to "authenticated";

grant truncate on table "public"."active_ingredient_interaction_dose_thresholds" to "authenticated";

grant update on table "public"."active_ingredient_interaction_dose_thresholds" to "authenticated";

grant delete on table "public"."active_ingredient_interaction_dose_thresholds" to "service_role";

grant insert on table "public"."active_ingredient_interaction_dose_thresholds" to "service_role";

grant references on table "public"."active_ingredient_interaction_dose_thresholds" to "service_role";

grant select on table "public"."active_ingredient_interaction_dose_thresholds" to "service_role";

grant trigger on table "public"."active_ingredient_interaction_dose_thresholds" to "service_role";

grant truncate on table "public"."active_ingredient_interaction_dose_thresholds" to "service_role";

grant update on table "public"."active_ingredient_interaction_dose_thresholds" to "service_role";

grant delete on table "public"."active_ingredient_interactions" to "anon";

grant insert on table "public"."active_ingredient_interactions" to "anon";

grant references on table "public"."active_ingredient_interactions" to "anon";

grant select on table "public"."active_ingredient_interactions" to "anon";

grant trigger on table "public"."active_ingredient_interactions" to "anon";

grant truncate on table "public"."active_ingredient_interactions" to "anon";

grant update on table "public"."active_ingredient_interactions" to "anon";

grant delete on table "public"."active_ingredient_interactions" to "authenticated";

grant insert on table "public"."active_ingredient_interactions" to "authenticated";

grant references on table "public"."active_ingredient_interactions" to "authenticated";

grant select on table "public"."active_ingredient_interactions" to "authenticated";

grant trigger on table "public"."active_ingredient_interactions" to "authenticated";

grant truncate on table "public"."active_ingredient_interactions" to "authenticated";

grant update on table "public"."active_ingredient_interactions" to "authenticated";

grant delete on table "public"."active_ingredient_interactions" to "service_role";

grant insert on table "public"."active_ingredient_interactions" to "service_role";

grant references on table "public"."active_ingredient_interactions" to "service_role";

grant select on table "public"."active_ingredient_interactions" to "service_role";

grant trigger on table "public"."active_ingredient_interactions" to "service_role";

grant truncate on table "public"."active_ingredient_interactions" to "service_role";

grant update on table "public"."active_ingredient_interactions" to "service_role";

grant delete on table "public"."active_ingredient_nhom_benh" to "anon";

grant insert on table "public"."active_ingredient_nhom_benh" to "anon";

grant references on table "public"."active_ingredient_nhom_benh" to "anon";

grant select on table "public"."active_ingredient_nhom_benh" to "anon";

grant trigger on table "public"."active_ingredient_nhom_benh" to "anon";

grant truncate on table "public"."active_ingredient_nhom_benh" to "anon";

grant update on table "public"."active_ingredient_nhom_benh" to "anon";

grant delete on table "public"."active_ingredient_nhom_benh" to "authenticated";

grant insert on table "public"."active_ingredient_nhom_benh" to "authenticated";

grant references on table "public"."active_ingredient_nhom_benh" to "authenticated";

grant select on table "public"."active_ingredient_nhom_benh" to "authenticated";

grant trigger on table "public"."active_ingredient_nhom_benh" to "authenticated";

grant truncate on table "public"."active_ingredient_nhom_benh" to "authenticated";

grant update on table "public"."active_ingredient_nhom_benh" to "authenticated";

grant delete on table "public"."active_ingredient_nhom_benh" to "service_role";

grant insert on table "public"."active_ingredient_nhom_benh" to "service_role";

grant references on table "public"."active_ingredient_nhom_benh" to "service_role";

grant select on table "public"."active_ingredient_nhom_benh" to "service_role";

grant trigger on table "public"."active_ingredient_nhom_benh" to "service_role";

grant truncate on table "public"."active_ingredient_nhom_benh" to "service_role";

grant update on table "public"."active_ingredient_nhom_benh" to "service_role";

grant delete on table "public"."active_ingredient_precautions" to "anon";

grant insert on table "public"."active_ingredient_precautions" to "anon";

grant references on table "public"."active_ingredient_precautions" to "anon";

grant select on table "public"."active_ingredient_precautions" to "anon";

grant trigger on table "public"."active_ingredient_precautions" to "anon";

grant truncate on table "public"."active_ingredient_precautions" to "anon";

grant update on table "public"."active_ingredient_precautions" to "anon";

grant delete on table "public"."active_ingredient_precautions" to "authenticated";

grant insert on table "public"."active_ingredient_precautions" to "authenticated";

grant references on table "public"."active_ingredient_precautions" to "authenticated";

grant select on table "public"."active_ingredient_precautions" to "authenticated";

grant trigger on table "public"."active_ingredient_precautions" to "authenticated";

grant truncate on table "public"."active_ingredient_precautions" to "authenticated";

grant update on table "public"."active_ingredient_precautions" to "authenticated";

grant delete on table "public"."active_ingredient_precautions" to "service_role";

grant insert on table "public"."active_ingredient_precautions" to "service_role";

grant references on table "public"."active_ingredient_precautions" to "service_role";

grant select on table "public"."active_ingredient_precautions" to "service_role";

grant trigger on table "public"."active_ingredient_precautions" to "service_role";

grant truncate on table "public"."active_ingredient_precautions" to "service_role";

grant update on table "public"."active_ingredient_precautions" to "service_role";

grant delete on table "public"."active_ingredients" to "anon";

grant insert on table "public"."active_ingredients" to "anon";

grant references on table "public"."active_ingredients" to "anon";

grant select on table "public"."active_ingredients" to "anon";

grant trigger on table "public"."active_ingredients" to "anon";

grant truncate on table "public"."active_ingredients" to "anon";

grant update on table "public"."active_ingredients" to "anon";

grant delete on table "public"."active_ingredients" to "authenticated";

grant insert on table "public"."active_ingredients" to "authenticated";

grant references on table "public"."active_ingredients" to "authenticated";

grant select on table "public"."active_ingredients" to "authenticated";

grant trigger on table "public"."active_ingredients" to "authenticated";

grant truncate on table "public"."active_ingredients" to "authenticated";

grant update on table "public"."active_ingredients" to "authenticated";

grant delete on table "public"."active_ingredients" to "service_role";

grant insert on table "public"."active_ingredients" to "service_role";

grant references on table "public"."active_ingredients" to "service_role";

grant select on table "public"."active_ingredients" to "service_role";

grant trigger on table "public"."active_ingredients" to "service_role";

grant truncate on table "public"."active_ingredients" to "service_role";

grant update on table "public"."active_ingredients" to "service_role";

grant delete on table "public"."caregiver_links" to "anon";

grant insert on table "public"."caregiver_links" to "anon";

grant references on table "public"."caregiver_links" to "anon";

grant select on table "public"."caregiver_links" to "anon";

grant trigger on table "public"."caregiver_links" to "anon";

grant truncate on table "public"."caregiver_links" to "anon";

grant update on table "public"."caregiver_links" to "anon";

grant delete on table "public"."caregiver_links" to "authenticated";

grant insert on table "public"."caregiver_links" to "authenticated";

grant references on table "public"."caregiver_links" to "authenticated";

grant select on table "public"."caregiver_links" to "authenticated";

grant trigger on table "public"."caregiver_links" to "authenticated";

grant truncate on table "public"."caregiver_links" to "authenticated";

grant update on table "public"."caregiver_links" to "authenticated";

grant delete on table "public"."caregiver_links" to "service_role";

grant insert on table "public"."caregiver_links" to "service_role";

grant references on table "public"."caregiver_links" to "service_role";

grant select on table "public"."caregiver_links" to "service_role";

grant trigger on table "public"."caregiver_links" to "service_role";

grant truncate on table "public"."caregiver_links" to "service_role";

grant update on table "public"."caregiver_links" to "service_role";

grant delete on table "public"."conditions" to "anon";

grant insert on table "public"."conditions" to "anon";

grant references on table "public"."conditions" to "anon";

grant select on table "public"."conditions" to "anon";

grant trigger on table "public"."conditions" to "anon";

grant truncate on table "public"."conditions" to "anon";

grant update on table "public"."conditions" to "anon";

grant delete on table "public"."conditions" to "authenticated";

grant insert on table "public"."conditions" to "authenticated";

grant references on table "public"."conditions" to "authenticated";

grant select on table "public"."conditions" to "authenticated";

grant trigger on table "public"."conditions" to "authenticated";

grant truncate on table "public"."conditions" to "authenticated";

grant update on table "public"."conditions" to "authenticated";

grant delete on table "public"."conditions" to "service_role";

grant insert on table "public"."conditions" to "service_role";

grant references on table "public"."conditions" to "service_role";

grant select on table "public"."conditions" to "service_role";

grant trigger on table "public"."conditions" to "service_role";

grant truncate on table "public"."conditions" to "service_role";

grant update on table "public"."conditions" to "service_role";

grant delete on table "public"."don_thuoc" to "anon";

grant insert on table "public"."don_thuoc" to "anon";

grant references on table "public"."don_thuoc" to "anon";

grant select on table "public"."don_thuoc" to "anon";

grant trigger on table "public"."don_thuoc" to "anon";

grant truncate on table "public"."don_thuoc" to "anon";

grant update on table "public"."don_thuoc" to "anon";

grant delete on table "public"."don_thuoc" to "authenticated";

grant insert on table "public"."don_thuoc" to "authenticated";

grant references on table "public"."don_thuoc" to "authenticated";

grant select on table "public"."don_thuoc" to "authenticated";

grant trigger on table "public"."don_thuoc" to "authenticated";

grant truncate on table "public"."don_thuoc" to "authenticated";

grant update on table "public"."don_thuoc" to "authenticated";

grant delete on table "public"."don_thuoc" to "service_role";

grant insert on table "public"."don_thuoc" to "service_role";

grant references on table "public"."don_thuoc" to "service_role";

grant select on table "public"."don_thuoc" to "service_role";

grant trigger on table "public"."don_thuoc" to "service_role";

grant truncate on table "public"."don_thuoc" to "service_role";

grant update on table "public"."don_thuoc" to "service_role";

grant delete on table "public"."dose_logs" to "anon";

grant insert on table "public"."dose_logs" to "anon";

grant references on table "public"."dose_logs" to "anon";

grant select on table "public"."dose_logs" to "anon";

grant trigger on table "public"."dose_logs" to "anon";

grant truncate on table "public"."dose_logs" to "anon";

grant update on table "public"."dose_logs" to "anon";

grant delete on table "public"."dose_logs" to "authenticated";

grant insert on table "public"."dose_logs" to "authenticated";

grant references on table "public"."dose_logs" to "authenticated";

grant select on table "public"."dose_logs" to "authenticated";

grant trigger on table "public"."dose_logs" to "authenticated";

grant truncate on table "public"."dose_logs" to "authenticated";

grant update on table "public"."dose_logs" to "authenticated";

grant delete on table "public"."dose_logs" to "service_role";

grant insert on table "public"."dose_logs" to "service_role";

grant references on table "public"."dose_logs" to "service_role";

grant select on table "public"."dose_logs" to "service_role";

grant trigger on table "public"."dose_logs" to "service_role";

grant truncate on table "public"."dose_logs" to "service_role";

grant update on table "public"."dose_logs" to "service_role";

grant delete on table "public"."drug_classes" to "anon";

grant insert on table "public"."drug_classes" to "anon";

grant references on table "public"."drug_classes" to "anon";

grant select on table "public"."drug_classes" to "anon";

grant trigger on table "public"."drug_classes" to "anon";

grant truncate on table "public"."drug_classes" to "anon";

grant update on table "public"."drug_classes" to "anon";

grant delete on table "public"."drug_classes" to "authenticated";

grant insert on table "public"."drug_classes" to "authenticated";

grant references on table "public"."drug_classes" to "authenticated";

grant select on table "public"."drug_classes" to "authenticated";

grant trigger on table "public"."drug_classes" to "authenticated";

grant truncate on table "public"."drug_classes" to "authenticated";

grant update on table "public"."drug_classes" to "authenticated";

grant delete on table "public"."drug_classes" to "service_role";

grant insert on table "public"."drug_classes" to "service_role";

grant references on table "public"."drug_classes" to "service_role";

grant select on table "public"."drug_classes" to "service_role";

grant trigger on table "public"."drug_classes" to "service_role";

grant truncate on table "public"."drug_classes" to "service_role";

grant update on table "public"."drug_classes" to "service_role";

grant delete on table "public"."drug_food_interactions" to "anon";

grant insert on table "public"."drug_food_interactions" to "anon";

grant references on table "public"."drug_food_interactions" to "anon";

grant select on table "public"."drug_food_interactions" to "anon";

grant trigger on table "public"."drug_food_interactions" to "anon";

grant truncate on table "public"."drug_food_interactions" to "anon";

grant update on table "public"."drug_food_interactions" to "anon";

grant delete on table "public"."drug_food_interactions" to "authenticated";

grant insert on table "public"."drug_food_interactions" to "authenticated";

grant references on table "public"."drug_food_interactions" to "authenticated";

grant select on table "public"."drug_food_interactions" to "authenticated";

grant trigger on table "public"."drug_food_interactions" to "authenticated";

grant truncate on table "public"."drug_food_interactions" to "authenticated";

grant update on table "public"."drug_food_interactions" to "authenticated";

grant delete on table "public"."drug_food_interactions" to "service_role";

grant insert on table "public"."drug_food_interactions" to "service_role";

grant references on table "public"."drug_food_interactions" to "service_role";

grant select on table "public"."drug_food_interactions" to "service_role";

grant trigger on table "public"."drug_food_interactions" to "service_role";

grant truncate on table "public"."drug_food_interactions" to "service_role";

grant update on table "public"."drug_food_interactions" to "service_role";

grant delete on table "public"."ingredient_aliases" to "anon";

grant insert on table "public"."ingredient_aliases" to "anon";

grant references on table "public"."ingredient_aliases" to "anon";

grant select on table "public"."ingredient_aliases" to "anon";

grant trigger on table "public"."ingredient_aliases" to "anon";

grant truncate on table "public"."ingredient_aliases" to "anon";

grant update on table "public"."ingredient_aliases" to "anon";

grant delete on table "public"."ingredient_aliases" to "authenticated";

grant insert on table "public"."ingredient_aliases" to "authenticated";

grant references on table "public"."ingredient_aliases" to "authenticated";

grant select on table "public"."ingredient_aliases" to "authenticated";

grant trigger on table "public"."ingredient_aliases" to "authenticated";

grant truncate on table "public"."ingredient_aliases" to "authenticated";

grant update on table "public"."ingredient_aliases" to "authenticated";

grant delete on table "public"."ingredient_aliases" to "service_role";

grant insert on table "public"."ingredient_aliases" to "service_role";

grant references on table "public"."ingredient_aliases" to "service_role";

grant select on table "public"."ingredient_aliases" to "service_role";

grant trigger on table "public"."ingredient_aliases" to "service_role";

grant truncate on table "public"."ingredient_aliases" to "service_role";

grant update on table "public"."ingredient_aliases" to "service_role";

grant delete on table "public"."kich_ban_benh_nhan_mau" to "anon";

grant insert on table "public"."kich_ban_benh_nhan_mau" to "anon";

grant references on table "public"."kich_ban_benh_nhan_mau" to "anon";

grant select on table "public"."kich_ban_benh_nhan_mau" to "anon";

grant trigger on table "public"."kich_ban_benh_nhan_mau" to "anon";

grant truncate on table "public"."kich_ban_benh_nhan_mau" to "anon";

grant update on table "public"."kich_ban_benh_nhan_mau" to "anon";

grant delete on table "public"."kich_ban_benh_nhan_mau" to "authenticated";

grant insert on table "public"."kich_ban_benh_nhan_mau" to "authenticated";

grant references on table "public"."kich_ban_benh_nhan_mau" to "authenticated";

grant select on table "public"."kich_ban_benh_nhan_mau" to "authenticated";

grant trigger on table "public"."kich_ban_benh_nhan_mau" to "authenticated";

grant truncate on table "public"."kich_ban_benh_nhan_mau" to "authenticated";

grant update on table "public"."kich_ban_benh_nhan_mau" to "authenticated";

grant delete on table "public"."kich_ban_benh_nhan_mau" to "service_role";

grant insert on table "public"."kich_ban_benh_nhan_mau" to "service_role";

grant references on table "public"."kich_ban_benh_nhan_mau" to "service_role";

grant select on table "public"."kich_ban_benh_nhan_mau" to "service_role";

grant trigger on table "public"."kich_ban_benh_nhan_mau" to "service_role";

grant truncate on table "public"."kich_ban_benh_nhan_mau" to "service_role";

grant update on table "public"."kich_ban_benh_nhan_mau" to "service_role";

grant delete on table "public"."kich_ban_dieu_kien" to "anon";

grant insert on table "public"."kich_ban_dieu_kien" to "anon";

grant references on table "public"."kich_ban_dieu_kien" to "anon";

grant select on table "public"."kich_ban_dieu_kien" to "anon";

grant trigger on table "public"."kich_ban_dieu_kien" to "anon";

grant truncate on table "public"."kich_ban_dieu_kien" to "anon";

grant update on table "public"."kich_ban_dieu_kien" to "anon";

grant delete on table "public"."kich_ban_dieu_kien" to "authenticated";

grant insert on table "public"."kich_ban_dieu_kien" to "authenticated";

grant references on table "public"."kich_ban_dieu_kien" to "authenticated";

grant select on table "public"."kich_ban_dieu_kien" to "authenticated";

grant trigger on table "public"."kich_ban_dieu_kien" to "authenticated";

grant truncate on table "public"."kich_ban_dieu_kien" to "authenticated";

grant update on table "public"."kich_ban_dieu_kien" to "authenticated";

grant delete on table "public"."kich_ban_dieu_kien" to "service_role";

grant insert on table "public"."kich_ban_dieu_kien" to "service_role";

grant references on table "public"."kich_ban_dieu_kien" to "service_role";

grant select on table "public"."kich_ban_dieu_kien" to "service_role";

grant trigger on table "public"."kich_ban_dieu_kien" to "service_role";

grant truncate on table "public"."kich_ban_dieu_kien" to "service_role";

grant update on table "public"."kich_ban_dieu_kien" to "service_role";

grant delete on table "public"."kich_ban_hoat_chat" to "anon";

grant insert on table "public"."kich_ban_hoat_chat" to "anon";

grant references on table "public"."kich_ban_hoat_chat" to "anon";

grant select on table "public"."kich_ban_hoat_chat" to "anon";

grant trigger on table "public"."kich_ban_hoat_chat" to "anon";

grant truncate on table "public"."kich_ban_hoat_chat" to "anon";

grant update on table "public"."kich_ban_hoat_chat" to "anon";

grant delete on table "public"."kich_ban_hoat_chat" to "authenticated";

grant insert on table "public"."kich_ban_hoat_chat" to "authenticated";

grant references on table "public"."kich_ban_hoat_chat" to "authenticated";

grant select on table "public"."kich_ban_hoat_chat" to "authenticated";

grant trigger on table "public"."kich_ban_hoat_chat" to "authenticated";

grant truncate on table "public"."kich_ban_hoat_chat" to "authenticated";

grant update on table "public"."kich_ban_hoat_chat" to "authenticated";

grant delete on table "public"."kich_ban_hoat_chat" to "service_role";

grant insert on table "public"."kich_ban_hoat_chat" to "service_role";

grant references on table "public"."kich_ban_hoat_chat" to "service_role";

grant select on table "public"."kich_ban_hoat_chat" to "service_role";

grant trigger on table "public"."kich_ban_hoat_chat" to "service_role";

grant truncate on table "public"."kich_ban_hoat_chat" to "service_role";

grant update on table "public"."kich_ban_hoat_chat" to "service_role";

grant delete on table "public"."meal_suggestions" to "anon";

grant insert on table "public"."meal_suggestions" to "anon";

grant references on table "public"."meal_suggestions" to "anon";

grant select on table "public"."meal_suggestions" to "anon";

grant trigger on table "public"."meal_suggestions" to "anon";

grant truncate on table "public"."meal_suggestions" to "anon";

grant update on table "public"."meal_suggestions" to "anon";

grant delete on table "public"."meal_suggestions" to "authenticated";

grant insert on table "public"."meal_suggestions" to "authenticated";

grant references on table "public"."meal_suggestions" to "authenticated";

grant select on table "public"."meal_suggestions" to "authenticated";

grant trigger on table "public"."meal_suggestions" to "authenticated";

grant truncate on table "public"."meal_suggestions" to "authenticated";

grant update on table "public"."meal_suggestions" to "authenticated";

grant delete on table "public"."meal_suggestions" to "service_role";

grant insert on table "public"."meal_suggestions" to "service_role";

grant references on table "public"."meal_suggestions" to "service_role";

grant select on table "public"."meal_suggestions" to "service_role";

grant trigger on table "public"."meal_suggestions" to "service_role";

grant truncate on table "public"."meal_suggestions" to "service_role";

grant update on table "public"."meal_suggestions" to "service_role";

grant delete on table "public"."medication_active_ingredients" to "anon";

grant insert on table "public"."medication_active_ingredients" to "anon";

grant references on table "public"."medication_active_ingredients" to "anon";

grant select on table "public"."medication_active_ingredients" to "anon";

grant trigger on table "public"."medication_active_ingredients" to "anon";

grant truncate on table "public"."medication_active_ingredients" to "anon";

grant update on table "public"."medication_active_ingredients" to "anon";

grant delete on table "public"."medication_active_ingredients" to "authenticated";

grant insert on table "public"."medication_active_ingredients" to "authenticated";

grant references on table "public"."medication_active_ingredients" to "authenticated";

grant select on table "public"."medication_active_ingredients" to "authenticated";

grant trigger on table "public"."medication_active_ingredients" to "authenticated";

grant truncate on table "public"."medication_active_ingredients" to "authenticated";

grant update on table "public"."medication_active_ingredients" to "authenticated";

grant delete on table "public"."medication_active_ingredients" to "service_role";

grant insert on table "public"."medication_active_ingredients" to "service_role";

grant references on table "public"."medication_active_ingredients" to "service_role";

grant select on table "public"."medication_active_ingredients" to "service_role";

grant trigger on table "public"."medication_active_ingredients" to "service_role";

grant truncate on table "public"."medication_active_ingredients" to "service_role";

grant update on table "public"."medication_active_ingredients" to "service_role";

grant delete on table "public"."medication_schedules" to "anon";

grant insert on table "public"."medication_schedules" to "anon";

grant references on table "public"."medication_schedules" to "anon";

grant select on table "public"."medication_schedules" to "anon";

grant trigger on table "public"."medication_schedules" to "anon";

grant truncate on table "public"."medication_schedules" to "anon";

grant update on table "public"."medication_schedules" to "anon";

grant delete on table "public"."medication_schedules" to "authenticated";

grant insert on table "public"."medication_schedules" to "authenticated";

grant references on table "public"."medication_schedules" to "authenticated";

grant select on table "public"."medication_schedules" to "authenticated";

grant trigger on table "public"."medication_schedules" to "authenticated";

grant truncate on table "public"."medication_schedules" to "authenticated";

grant update on table "public"."medication_schedules" to "authenticated";

grant delete on table "public"."medication_schedules" to "service_role";

grant insert on table "public"."medication_schedules" to "service_role";

grant references on table "public"."medication_schedules" to "service_role";

grant select on table "public"."medication_schedules" to "service_role";

grant trigger on table "public"."medication_schedules" to "service_role";

grant truncate on table "public"."medication_schedules" to "service_role";

grant update on table "public"."medication_schedules" to "service_role";

grant delete on table "public"."medications" to "anon";

grant insert on table "public"."medications" to "anon";

grant references on table "public"."medications" to "anon";

grant select on table "public"."medications" to "anon";

grant trigger on table "public"."medications" to "anon";

grant truncate on table "public"."medications" to "anon";

grant update on table "public"."medications" to "anon";

grant delete on table "public"."medications" to "authenticated";

grant insert on table "public"."medications" to "authenticated";

grant references on table "public"."medications" to "authenticated";

grant select on table "public"."medications" to "authenticated";

grant trigger on table "public"."medications" to "authenticated";

grant truncate on table "public"."medications" to "authenticated";

grant update on table "public"."medications" to "authenticated";

grant delete on table "public"."medications" to "service_role";

grant insert on table "public"."medications" to "service_role";

grant references on table "public"."medications" to "service_role";

grant select on table "public"."medications" to "service_role";

grant trigger on table "public"."medications" to "service_role";

grant truncate on table "public"."medications" to "service_role";

grant update on table "public"."medications" to "service_role";

grant delete on table "public"."notifications" to "anon";

grant insert on table "public"."notifications" to "anon";

grant references on table "public"."notifications" to "anon";

grant select on table "public"."notifications" to "anon";

grant trigger on table "public"."notifications" to "anon";

grant truncate on table "public"."notifications" to "anon";

grant update on table "public"."notifications" to "anon";

grant delete on table "public"."notifications" to "authenticated";

grant insert on table "public"."notifications" to "authenticated";

grant references on table "public"."notifications" to "authenticated";

grant select on table "public"."notifications" to "authenticated";

grant trigger on table "public"."notifications" to "authenticated";

grant truncate on table "public"."notifications" to "authenticated";

grant update on table "public"."notifications" to "authenticated";

grant delete on table "public"."notifications" to "service_role";

grant insert on table "public"."notifications" to "service_role";

grant references on table "public"."notifications" to "service_role";

grant select on table "public"."notifications" to "service_role";

grant trigger on table "public"."notifications" to "service_role";

grant truncate on table "public"."notifications" to "service_role";

grant update on table "public"."notifications" to "service_role";

grant delete on table "public"."regimen_analysis_finding_don_thuoc" to "anon";

grant insert on table "public"."regimen_analysis_finding_don_thuoc" to "anon";

grant references on table "public"."regimen_analysis_finding_don_thuoc" to "anon";

grant select on table "public"."regimen_analysis_finding_don_thuoc" to "anon";

grant trigger on table "public"."regimen_analysis_finding_don_thuoc" to "anon";

grant truncate on table "public"."regimen_analysis_finding_don_thuoc" to "anon";

grant update on table "public"."regimen_analysis_finding_don_thuoc" to "anon";

grant delete on table "public"."regimen_analysis_finding_don_thuoc" to "authenticated";

grant insert on table "public"."regimen_analysis_finding_don_thuoc" to "authenticated";

grant references on table "public"."regimen_analysis_finding_don_thuoc" to "authenticated";

grant select on table "public"."regimen_analysis_finding_don_thuoc" to "authenticated";

grant trigger on table "public"."regimen_analysis_finding_don_thuoc" to "authenticated";

grant truncate on table "public"."regimen_analysis_finding_don_thuoc" to "authenticated";

grant update on table "public"."regimen_analysis_finding_don_thuoc" to "authenticated";

grant delete on table "public"."regimen_analysis_finding_don_thuoc" to "service_role";

grant insert on table "public"."regimen_analysis_finding_don_thuoc" to "service_role";

grant references on table "public"."regimen_analysis_finding_don_thuoc" to "service_role";

grant select on table "public"."regimen_analysis_finding_don_thuoc" to "service_role";

grant trigger on table "public"."regimen_analysis_finding_don_thuoc" to "service_role";

grant truncate on table "public"."regimen_analysis_finding_don_thuoc" to "service_role";

grant update on table "public"."regimen_analysis_finding_don_thuoc" to "service_role";

grant delete on table "public"."regimen_analysis_findings" to "anon";

grant insert on table "public"."regimen_analysis_findings" to "anon";

grant references on table "public"."regimen_analysis_findings" to "anon";

grant select on table "public"."regimen_analysis_findings" to "anon";

grant trigger on table "public"."regimen_analysis_findings" to "anon";

grant truncate on table "public"."regimen_analysis_findings" to "anon";

grant update on table "public"."regimen_analysis_findings" to "anon";

grant delete on table "public"."regimen_analysis_findings" to "authenticated";

grant insert on table "public"."regimen_analysis_findings" to "authenticated";

grant references on table "public"."regimen_analysis_findings" to "authenticated";

grant select on table "public"."regimen_analysis_findings" to "authenticated";

grant trigger on table "public"."regimen_analysis_findings" to "authenticated";

grant truncate on table "public"."regimen_analysis_findings" to "authenticated";

grant update on table "public"."regimen_analysis_findings" to "authenticated";

grant delete on table "public"."regimen_analysis_findings" to "service_role";

grant insert on table "public"."regimen_analysis_findings" to "service_role";

grant references on table "public"."regimen_analysis_findings" to "service_role";

grant select on table "public"."regimen_analysis_findings" to "service_role";

grant trigger on table "public"."regimen_analysis_findings" to "service_role";

grant truncate on table "public"."regimen_analysis_findings" to "service_role";

grant update on table "public"."regimen_analysis_findings" to "service_role";

grant delete on table "public"."regimen_analysis_snapshots" to "anon";

grant insert on table "public"."regimen_analysis_snapshots" to "anon";

grant references on table "public"."regimen_analysis_snapshots" to "anon";

grant select on table "public"."regimen_analysis_snapshots" to "anon";

grant trigger on table "public"."regimen_analysis_snapshots" to "anon";

grant truncate on table "public"."regimen_analysis_snapshots" to "anon";

grant update on table "public"."regimen_analysis_snapshots" to "anon";

grant delete on table "public"."regimen_analysis_snapshots" to "authenticated";

grant insert on table "public"."regimen_analysis_snapshots" to "authenticated";

grant references on table "public"."regimen_analysis_snapshots" to "authenticated";

grant select on table "public"."regimen_analysis_snapshots" to "authenticated";

grant trigger on table "public"."regimen_analysis_snapshots" to "authenticated";

grant truncate on table "public"."regimen_analysis_snapshots" to "authenticated";

grant update on table "public"."regimen_analysis_snapshots" to "authenticated";

grant delete on table "public"."regimen_analysis_snapshots" to "service_role";

grant insert on table "public"."regimen_analysis_snapshots" to "service_role";

grant references on table "public"."regimen_analysis_snapshots" to "service_role";

grant select on table "public"."regimen_analysis_snapshots" to "service_role";

grant trigger on table "public"."regimen_analysis_snapshots" to "service_role";

grant truncate on table "public"."regimen_analysis_snapshots" to "service_role";

grant update on table "public"."regimen_analysis_snapshots" to "service_role";

grant delete on table "public"."user_conditions" to "anon";

grant insert on table "public"."user_conditions" to "anon";

grant references on table "public"."user_conditions" to "anon";

grant select on table "public"."user_conditions" to "anon";

grant trigger on table "public"."user_conditions" to "anon";

grant truncate on table "public"."user_conditions" to "anon";

grant update on table "public"."user_conditions" to "anon";

grant delete on table "public"."user_conditions" to "authenticated";

grant insert on table "public"."user_conditions" to "authenticated";

grant references on table "public"."user_conditions" to "authenticated";

grant select on table "public"."user_conditions" to "authenticated";

grant trigger on table "public"."user_conditions" to "authenticated";

grant truncate on table "public"."user_conditions" to "authenticated";

grant update on table "public"."user_conditions" to "authenticated";

grant delete on table "public"."user_conditions" to "service_role";

grant insert on table "public"."user_conditions" to "service_role";

grant references on table "public"."user_conditions" to "service_role";

grant select on table "public"."user_conditions" to "service_role";

grant trigger on table "public"."user_conditions" to "service_role";

grant truncate on table "public"."user_conditions" to "service_role";

grant update on table "public"."user_conditions" to "service_role";

grant delete on table "public"."user_consents" to "anon";

grant insert on table "public"."user_consents" to "anon";

grant references on table "public"."user_consents" to "anon";

grant select on table "public"."user_consents" to "anon";

grant trigger on table "public"."user_consents" to "anon";

grant truncate on table "public"."user_consents" to "anon";

grant update on table "public"."user_consents" to "anon";

grant delete on table "public"."user_consents" to "authenticated";

grant insert on table "public"."user_consents" to "authenticated";

grant references on table "public"."user_consents" to "authenticated";

grant select on table "public"."user_consents" to "authenticated";

grant trigger on table "public"."user_consents" to "authenticated";

grant truncate on table "public"."user_consents" to "authenticated";

grant update on table "public"."user_consents" to "authenticated";

grant delete on table "public"."user_consents" to "service_role";

grant insert on table "public"."user_consents" to "service_role";

grant references on table "public"."user_consents" to "service_role";

grant select on table "public"."user_consents" to "service_role";

grant trigger on table "public"."user_consents" to "service_role";

grant truncate on table "public"."user_consents" to "service_role";

grant update on table "public"."user_consents" to "service_role";

grant delete on table "public"."user_medications" to "anon";

grant insert on table "public"."user_medications" to "anon";

grant references on table "public"."user_medications" to "anon";

grant select on table "public"."user_medications" to "anon";

grant trigger on table "public"."user_medications" to "anon";

grant truncate on table "public"."user_medications" to "anon";

grant update on table "public"."user_medications" to "anon";

grant delete on table "public"."user_medications" to "authenticated";

grant insert on table "public"."user_medications" to "authenticated";

grant references on table "public"."user_medications" to "authenticated";

grant select on table "public"."user_medications" to "authenticated";

grant trigger on table "public"."user_medications" to "authenticated";

grant truncate on table "public"."user_medications" to "authenticated";

grant update on table "public"."user_medications" to "authenticated";

grant delete on table "public"."user_medications" to "service_role";

grant insert on table "public"."user_medications" to "service_role";

grant references on table "public"."user_medications" to "service_role";

grant select on table "public"."user_medications" to "service_role";

grant trigger on table "public"."user_medications" to "service_role";

grant truncate on table "public"."user_medications" to "service_role";

grant update on table "public"."user_medications" to "service_role";

grant delete on table "public"."user_recommendations" to "anon";

grant insert on table "public"."user_recommendations" to "anon";

grant references on table "public"."user_recommendations" to "anon";

grant select on table "public"."user_recommendations" to "anon";

grant trigger on table "public"."user_recommendations" to "anon";

grant truncate on table "public"."user_recommendations" to "anon";

grant update on table "public"."user_recommendations" to "anon";

grant delete on table "public"."user_recommendations" to "authenticated";

grant insert on table "public"."user_recommendations" to "authenticated";

grant references on table "public"."user_recommendations" to "authenticated";

grant select on table "public"."user_recommendations" to "authenticated";

grant trigger on table "public"."user_recommendations" to "authenticated";

grant truncate on table "public"."user_recommendations" to "authenticated";

grant update on table "public"."user_recommendations" to "authenticated";

grant delete on table "public"."user_recommendations" to "service_role";

grant insert on table "public"."user_recommendations" to "service_role";

grant references on table "public"."user_recommendations" to "service_role";

grant select on table "public"."user_recommendations" to "service_role";

grant trigger on table "public"."user_recommendations" to "service_role";

grant truncate on table "public"."user_recommendations" to "service_role";

grant update on table "public"."user_recommendations" to "service_role";

grant delete on table "public"."users" to "anon";

grant insert on table "public"."users" to "anon";

grant references on table "public"."users" to "anon";

grant select on table "public"."users" to "anon";

grant trigger on table "public"."users" to "anon";

grant truncate on table "public"."users" to "anon";

grant update on table "public"."users" to "anon";

grant delete on table "public"."users" to "authenticated";

grant insert on table "public"."users" to "authenticated";

grant references on table "public"."users" to "authenticated";

grant select on table "public"."users" to "authenticated";

grant trigger on table "public"."users" to "authenticated";

grant truncate on table "public"."users" to "authenticated";

grant update on table "public"."users" to "authenticated";

grant delete on table "public"."users" to "service_role";

grant insert on table "public"."users" to "service_role";

grant references on table "public"."users" to "service_role";

grant select on table "public"."users" to "service_role";

grant trigger on table "public"."users" to "service_role";

grant truncate on table "public"."users" to "service_role";

grant update on table "public"."users" to "service_role";


