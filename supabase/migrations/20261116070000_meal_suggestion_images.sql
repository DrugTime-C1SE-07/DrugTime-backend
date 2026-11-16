-- Task 5.11: meal images (Pexels → Storage), refresh tracking for meal suggestions.
-- Images are shared per dish, never tied to a user, and hold no health data.

-- 1. meal_suggestions: reference to the suggestion a refresh started from.
--    Nullable without default: no table rewrite; existing rows stay unchanged.
ALTER TABLE meal_suggestions
    ADD COLUMN previous_suggestion_id bigint NULL
        REFERENCES meal_suggestions (id) ON DELETE SET NULL;

-- Daily refresh count per user (AC27).
CREATE INDEX meal_suggestions_refresh_idx ON meal_suggestions (user_id, created_at)
    WHERE previous_suggestion_id IS NOT NULL;

-- 2. meal_images: one row per normalized dish name.
CREATE TABLE meal_images (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dish_key text NOT NULL UNIQUE CHECK (length(dish_key) BETWEEN 1 AND 120),
    image_query text NOT NULL CHECK (length(image_query) BETWEEN 1 AND 60),
    status text NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
    storage_path text CHECK (storage_path IS NULL OR length(storage_path) BETWEEN 1 AND 200),
    content_type text CHECK (content_type IN ('image/jpeg', 'image/png', 'image/webp')),
    size_bytes integer CHECK (size_bytes BETWEEN 1 AND 2097152),
    provider text CHECK (provider = 'pexels'),
    provider_photo_id text CHECK (provider_photo_id IS NULL OR length(provider_photo_id) <= 64),
    photographer_name text CHECK (photographer_name IS NULL OR length(photographer_name) BETWEEN 1 AND 120),
    photographer_url text CHECK (photographer_url IS NULL OR length(photographer_url) BETWEEN 1 AND 500),
    source_url text CHECK (source_url IS NULL OR length(source_url) BETWEEN 1 AND 500),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'ready' OR (
        storage_path IS NOT NULL AND content_type IS NOT NULL AND size_bytes IS NOT NULL
        AND provider IS NOT NULL AND photographer_name IS NOT NULL
        AND photographer_url IS NOT NULL AND source_url IS NOT NULL
    ))
);

ALTER TABLE meal_images ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON meal_images FROM PUBLIC, anon, authenticated, service_role, api_role, worker_role;
-- API only reads; it creates/reuses rows solely through ai_meal_reserve_image (AC23).
GRANT SELECT ON meal_images TO api_role;
-- Worker reads pending rows and records the outcome.
GRANT SELECT, UPDATE ON meal_images TO worker_role;
CREATE POLICY meal_images_api_select ON meal_images FOR SELECT TO api_role USING (true);
CREATE POLICY meal_images_worker_select ON meal_images FOR SELECT TO worker_role USING (true);
CREATE POLICY meal_images_worker_update ON meal_images FOR UPDATE TO worker_role
    USING (true) WITH CHECK (true);

-- 3. Narrow write path for the API: reserve (or reuse) the image row of a dish.
--    pending younger than 2 minutes → reuse; ready → reuse;
--    failed / stale pending → retry only when last touched more than 24 hours ago.
CREATE FUNCTION ai_meal_reserve_image(p_dish_key text, p_query text)
RETURNS TABLE (image_id bigint, status text, enqueue boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
    r meal_images%ROWTYPE;
BEGIN
    IF p_dish_key IS NULL OR length(p_dish_key) NOT BETWEEN 1 AND 120
       OR p_query IS NULL OR length(p_query) NOT BETWEEN 1 AND 60 THEN
        RAISE EXCEPTION 'invalid meal image reservation' USING ERRCODE = '22023';
    END IF;

    INSERT INTO meal_images (dish_key, image_query, status)
    VALUES (p_dish_key, p_query, 'pending')
    ON CONFLICT (dish_key) DO NOTHING
    RETURNING * INTO r;
    IF FOUND THEN
        RETURN QUERY SELECT r.id, 'pending'::text, true;
        RETURN;
    END IF;

    SELECT * INTO r FROM meal_images m WHERE m.dish_key = p_dish_key FOR UPDATE;
    IF r.status = 'ready' THEN
        RETURN QUERY SELECT r.id, 'ready'::text, false;
    ELSIF r.status = 'pending' AND r.updated_at >= now() - interval '2 minutes' THEN
        RETURN QUERY SELECT r.id, 'pending'::text, false;
    ELSIF r.updated_at < now() - interval '24 hours' THEN
        UPDATE meal_images m
        SET status = 'pending', image_query = p_query, updated_at = now()
        WHERE m.id = r.id;
        RETURN QUERY SELECT r.id, 'pending'::text, true;
    ELSE
        RETURN QUERY SELECT r.id, 'failed'::text, false;
    END IF;
END
$$;

REVOKE ALL ON FUNCTION ai_meal_reserve_image(text, text)
    FROM PUBLIC, anon, authenticated, service_role, worker_role;
GRANT EXECUTE ON FUNCTION ai_meal_reserve_image(text, text) TO api_role;

-- 4. Private bucket. No policy on storage.objects: only the server-side service key reaches it.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('meal-images', 'meal-images', false, 2097152,
        ARRAY['image/jpeg', 'image/png', 'image/webp'])
ON CONFLICT (id) DO NOTHING;
