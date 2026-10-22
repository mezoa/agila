-- FR7 (block g, Eo's option 1, 2026-10-22): one active document per identity for web pages only.
-- Two different text or Markdown notes may share a label; library.py warns instead.
DROP INDEX documents_active_identity;
CREATE UNIQUE INDEX documents_active_identity
    ON documents (space_id, identity_key)
    WHERE status = 'active' AND source_type = 'web';
