-- Application history table, backing services/application_tracker.py.
-- Records jobs a user has tailored a resume for or applied to.
--
-- Run this in the Supabase SQL Editor (Project > SQL Editor > New query) for
-- your project, or via `psql`/the Supabase CLI if you manage schema that way.
-- The REST API (used everywhere else in this app, via supabase_request) can
-- only do row-level CRUD, not DDL, so this can't be applied from the app itself.

create table if not exists public.applications (
    id          bigint generated always as identity primary key,
    user_id     bigint not null references public.users(id) on delete cascade,
    job_title   text not null default '',
    company     text not null default '',
    job_url     text not null default '',
    score       integer,
    status      text not null default 'tailored',
    created_at  timestamptz not null default now()
);

-- Every list_applications() call filters by user_id and sorts by created_at desc.
create index if not exists applications_user_id_created_at_idx
    on public.applications (user_id, created_at desc);

alter table public.applications enable row level security;

-- NOTE: SUPABASE_KEY in this project is NOT a service-role key (verified live —
-- it can read/write users/sessions, which have no RLS, but was blocked by RLS
-- here). A real service-role key bypasses RLS unconditionally, so this policy
-- is required for the app's actual key to write/read this table at all. This
-- matches the (lack of) protection already on users/sessions/user_resumes.
-- If you later rotate SUPABASE_KEY to the real service-role key (Project
-- Settings > API), you can drop this policy without breaking the app.
create policy "App key full access to applications"
    on public.applications
    for all
    using (true)
    with check (true);
