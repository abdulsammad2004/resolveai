CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- API runtime role: not a superuser, never owns tables, so RLS always applies.
CREATE ROLE resolveai_app LOGIN PASSWORD 'resolveai_app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

GRANT USAGE ON SCHEMA public TO resolveai_app;
ALTER DEFAULT PRIVILEGES FOR ROLE resolveai IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO resolveai_app;
ALTER DEFAULT PRIVILEGES FOR ROLE resolveai IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO resolveai_app;

-- Test database with the same extensions and privileges.
CREATE DATABASE resolveai_test OWNER resolveai;

\connect resolveai_test

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

GRANT USAGE ON SCHEMA public TO resolveai_app;
ALTER DEFAULT PRIVILEGES FOR ROLE resolveai IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO resolveai_app;
ALTER DEFAULT PRIVILEGES FOR ROLE resolveai IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO resolveai_app;
