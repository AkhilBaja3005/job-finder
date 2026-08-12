-- Add sync_code column to users table for Chrome Extension 6-Digit pairing
--
-- Run this in the Supabase SQL Editor (Project > SQL Editor > New query)

ALTER TABLE public.users
ADD COLUMN IF NOT EXISTS sync_code text UNIQUE;

CREATE INDEX IF NOT EXISTS users_sync_code_idx
    ON public.users (sync_code);
