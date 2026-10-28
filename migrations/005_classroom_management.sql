-- Stable teacher-only enrollment codes and voluntary membership departures.
-- Application tables remain API-only under the grants/RLS in migration 002.
BEGIN;
ALTER TABLE public.courses ADD COLUMN IF NOT EXISTS enrollment_code varchar(80);
ALTER TABLE public.courses ADD COLUMN IF NOT EXISTS enrollment_enabled boolean NOT NULL DEFAULT true;
CREATE UNIQUE INDEX IF NOT EXISTS courses_enrollment_code_unique
    ON public.courses (enrollment_code) WHERE enrollment_code IS NOT NULL;
ALTER TABLE public.memberships ADD COLUMN IF NOT EXISTS left_voluntarily boolean NOT NULL DEFAULT false;
-- Preserve previously disabled/unissued enrollment. Hash-only legacy codes
-- stay valid when a permanent visible code is first allocated by the teacher.
UPDATE public.courses SET enrollment_enabled = false
    WHERE enrollment_hash IS NULL AND enrollment_code IS NULL;
COMMIT;
