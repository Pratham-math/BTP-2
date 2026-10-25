-- Supabase does not delegate auth-schema USAGE to application roles. Expose only
-- a boolean check of an already JWT-verified session, not direct session rows.
CREATE FUNCTION public.btp2_session_active(p_session_id uuid, p_user_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1 FROM auth.sessions AS s
    WHERE s.id = p_session_id AND s.user_id = p_user_id
      AND (s.not_after IS NULL OR s.not_after > pg_catalog.now())
  );
$$;
REVOKE ALL ON FUNCTION public.btp2_session_active(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.btp2_session_active(uuid, uuid) TO btp2_backend;
REVOKE SELECT (id, user_id, not_after) ON auth.sessions FROM btp2_backend;
