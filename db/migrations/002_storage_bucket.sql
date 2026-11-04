-- Private bucket for original uploads. Only runs on Supabase (schema "storage" exists there).
-- public = false: files are reachable only through short-lived signed URLs issued to admins.
do $$
begin
  if exists (select 1 from information_schema.schemata where schema_name = 'storage') then
    insert into storage.buckets (id, name, public) values ('batch-files', 'batch-files', false)
    on conflict (id) do update set public = false;
  end if;
end $$;
