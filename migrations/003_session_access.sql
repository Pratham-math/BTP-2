-- Read only the columns needed to reject revoked/expired Supabase sessions.
GRANT USAGE ON SCHEMA auth TO btp2_backend;
GRANT SELECT (id, user_id, not_after) ON auth.sessions TO btp2_backend;

CREATE FUNCTION btp2_immutable_asset() RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
DECLARE block_state text;
BEGIN
  SELECT state INTO block_state FROM blocks WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.block_id ELSE NEW.block_id END;
  IF block_state = 'ready' THEN
    RAISE EXCEPTION 'Ready assets are immutable; create a new block version';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_asset BEFORE INSERT OR UPDATE OR DELETE ON assets FOR EACH ROW EXECUTE FUNCTION btp2_immutable_asset();
