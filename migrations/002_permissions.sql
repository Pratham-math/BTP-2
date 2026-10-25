-- The browser uses Supabase Auth only. Application records are API-only.
-- There is deliberately no direct anon/authenticated access to private data.
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'profiles','courses','memberships','sources','source_versions','lessons',
    'curricula','blocks','assets','assessments','reviews','assignments',
    'learning_sessions','attempts','jobs','stage_results','issues','audit_events'
  ] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', table_name);
  END LOOP;
END $$;

-- Use a dedicated backend LOGIN role, never a browser publishable/service key.
-- Grant it only DML; migrations and role provisioning use the operator role.
-- The backend checks every identity and scope; backend RLS is a distinct policy.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'btp2_backend') THEN
    CREATE ROLE btp2_backend NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO btp2_backend;
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'profiles','courses','memberships','sources','source_versions','lessons',
    'curricula','blocks','assets','assessments','reviews','assignments',
    'learning_sessions','attempts','jobs','stage_results','issues','audit_events'
  ] LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO btp2_backend', table_name);
    EXECUTE format('CREATE POLICY backend_access ON public.%I TO btp2_backend USING (true) WITH CHECK (true)', table_name);
  END LOOP;
END $$;

-- Versioned values are constrained even if a caller bypasses Pydantic.
ALTER TABLE profiles ADD CONSTRAINT profile_privilege CHECK (privilege IN ('student','teacher','administrator'));
ALTER TABLE jobs ADD CONSTRAINT job_state CHECK (state IN ('queued','running','waiting_for_input','waiting_for_review','failed','cancelled','completed'));
ALTER TABLE jobs ADD CONSTRAINT job_priority CHECK (priority BETWEEN 0 AND 2);
ALTER TABLE blocks ADD CONSTRAINT block_state CHECK (state IN ('planned','authoring','verified','rendering','playable','ready','failed'));
ALTER TABLE curricula ADD CONSTRAINT publication_state CHECK (publication IN ('draft','approved','published','suspended','retired'));
ALTER TABLE assets ADD CONSTRAINT asset_duration CHECK (duration > 0);
ALTER TABLE learning_sessions ADD CONSTRAINT session_revisions CHECK (revision > 0 AND route_revision > 0);

-- Approval locks source curriculum, keys and scripts. Publication/availability
-- metadata may change (e.g. suspension), but content edits require a new version.
CREATE FUNCTION btp2_immutable_content() RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
DECLARE version_state text;
BEGIN
  IF TG_TABLE_NAME = 'curricula' THEN
    IF OLD.publication <> 'draft' AND NEW.blueprint::jsonb IS DISTINCT FROM OLD.blueprint::jsonb THEN
      RAISE EXCEPTION 'Approved curriculum content is immutable';
    END IF;
  ELSE
    SELECT publication INTO version_state FROM curricula WHERE id = OLD.curriculum_id;
    IF version_state <> 'draft' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
      RAISE EXCEPTION 'Approved teaching content is immutable';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_curriculum BEFORE UPDATE ON curricula FOR EACH ROW EXECUTE FUNCTION btp2_immutable_content();
CREATE TRIGGER immutable_block BEFORE UPDATE ON blocks FOR EACH ROW EXECUTE FUNCTION btp2_immutable_content();
CREATE TRIGGER immutable_assessment BEFORE UPDATE ON assessments FOR EACH ROW EXECUTE FUNCTION btp2_immutable_content();
