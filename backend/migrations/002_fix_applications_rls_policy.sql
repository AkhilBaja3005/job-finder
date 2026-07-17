-- Fixes applications table access: the app's SUPABASE_KEY was found (via a
-- live diagnostic write) to NOT be a service-role key — it's blocked by RLS
-- with no policies, unlike users/sessions/user_resumes which have no RLS at
-- all. This grants the same (lack of) restriction those tables already have,
-- so the app's actual key can read/write this table.
--
-- Run this in the Supabase SQL Editor after 001_create_applications_table.sql
-- has already been applied.

create policy "App key full access to applications"
    on public.applications
    for all
    using (true)
    with check (true);
