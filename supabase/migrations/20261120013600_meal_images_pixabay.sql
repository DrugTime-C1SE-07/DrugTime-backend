-- Task adhoc-20261120-pixabay-meal-images: meal images now come from Pixabay only.
-- Pexels no longer issues API keys, so every image row from the Pexels era is dropped
-- (ready, pending and failed alike; pending/failed rows have a NULL provider).
-- meal_images is a per-dish image cache: it holds no health data and no foreign key
-- points to it. A dropped dish is reserved again (new id) on its next suggestion.
-- Stored objects in the meal-images bucket are not removed here: SQL must not delete
-- storage.objects directly; old files are keyed by the old ids and are never reused.

DELETE FROM meal_images WHERE provider IS DISTINCT FROM 'pixabay';

-- Delete first: ADD CONSTRAINT validates existing rows.
ALTER TABLE meal_images DROP CONSTRAINT IF EXISTS meal_images_provider_check;
ALTER TABLE meal_images
    ADD CONSTRAINT meal_images_provider_check CHECK (provider = 'pixabay');
