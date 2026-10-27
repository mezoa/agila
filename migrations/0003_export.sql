-- FR28 (block n, Eo, 2026-10-27): a document stays export_pending until its Obsidian note is
-- written. Existing rows start as true, so the first `export --retry` writes their notes.
-- original_path keeps a PDF's source path, so a retry can copy a missing original.
ALTER TABLE documents
    ADD COLUMN export_pending boolean NOT NULL DEFAULT true,
    ADD COLUMN original_path text;
