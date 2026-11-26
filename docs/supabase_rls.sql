-- Row-level security for the Job Finder tables.
--
-- WHY: with a publishable (anon) key, anyone who has the key can read these tables unless RLS is on.
-- They hold emails, sync codes, resumes and saved API keys.
--
-- ORDER MATTERS. Do these in this order, or the server loses access:
--   1. Supabase dashboard -> Project Settings -> API Keys -> create a SECRET key (starts with sb_secret_).
--   2. Put it in the server's secrets as SUPABASE_SERVICE_KEY (Hugging Face Space secret, and the CLI .env).
--      Restart the server and check that logins and uploads still work.
--   3. Run this file in the SQL editor.
--
-- The server uses the secret key, which bypasses RLS. With no policies for anon or authenticated,
-- those roles can read and write nothing.

alter table if exists public.users        enable row level security;
alter table if exists public.sessions     enable row level security;
alter table if exists public.user_resumes enable row level security;
alter table if exists public.applications enable row level security;

revoke all on public.users        from anon, authenticated;
revoke all on public.sessions     from anon, authenticated;
revoke all on public.user_resumes from anon, authenticated;
revoke all on public.applications from anon, authenticated;

-- Check afterwards (should return 401/403 or no rows, using the publishable key):
--   curl -s "$SUPABASE_URL/rest/v1/users?select=id&limit=1" -H "apikey: $PUBLISHABLE_KEY"
-- Then rotate the publishable key if it was ever shared.
