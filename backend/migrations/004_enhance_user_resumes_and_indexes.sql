-- 004_enhance_user_resumes_and_indexes.sql
-- Applied to Supabase project iileqpgzppssrsjdseia via MCP

ALTER TABLE public.user_resumes 
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now());

CREATE INDEX IF NOT EXISTS idx_user_resumes_user_id ON public.user_resumes(user_id);
CREATE INDEX IF NOT EXISTS idx_applications_user_id ON public.applications(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON public.sessions(user_id);
