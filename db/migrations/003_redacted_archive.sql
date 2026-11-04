-- Originals are redacted before archiving (supplier discount columns removed). file_sha256 stays the hash of the
-- file as uploaded (duplicate detection); stored_sha256 is the hash of the redacted copy actually archived.
alter table import_batches add column stored_sha256 text;
alter table import_batches add column redacted boolean not null default false;
