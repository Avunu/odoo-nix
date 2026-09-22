# Migration fixtures

Later versions of `tests/fixtures/<series>/custom/odoo_nix_fixture` (1.0.0),
for the checks that migrate a database from one build to the next
(`cli-migrate-<major>` in tests/series.nix, `module-odoo-<major>`). Each
directory is a workspace root holding only `custom/`: OCB comes from the
series' `ocb-*` input and the Python env from that series' fixture, so the
addon is the only thing that differs between builds. Version numbers carry no
series prefix, so the same trees serve 18.0 and 19.0.

- `v2` (1.0.1): adds a field on `res.partner` (a column only an update
  creates) and a post-migrate script that records it ran.
- `v3` (1.0.2): v2 plus a pre-migrate script that commits a change and then
  raises -- a migration that fails *after* touching the database, which is
  what a rollback has to undo.
