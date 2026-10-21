---
title: Development guard rails
description: The devguard options that stop a database restored from production from mailing customers, calling integrations, writing to production storage or running its backups, and the limits of that protection.
order: 4
tags: [devguard, security, mail, egress]
updated: 2026-10-21
---

A database restored from production carries working production credentials: SMTP and IMAP logins, S3 keys, API tokens, webhook URLs, an SFTP backup target. Left alone it will mail real customers, push a dev-mutated database over the production backup rotation, delete production files and call every integration it has a key for. Odoo's neutralization covers what Odoo and a few addons remember to cover (mail servers, crons, webhook URLs, OAuth, IAP, payment providers). `odoo_devguard` closes the rest, and holds when neutralization was skipped or an addon ships no `neutralize.sql`, which most do not.

## How it is installed

`odoo_devguard` is a small Python package grafted into the dev and test virtualenvs with a `.pth` file, and never into the production one, so `services.odoo-nix` and the container image cannot contain it. Every interpreter started from that environment is covered at startup, below Odoo: the server, `odoo shell`, `odoo db …`, an editor's terminal, an ad-hoc script. There is no module to install into a database and no `odoo.conf` edit. `devguard.enable` (on by default) switches the whole thing.

## The guards

| Guard | What it does | Option |
| --- | --- | --- |
| `egress` | The catch-all. Refuses every `connect()` the process makes to a non-loopback address: requests, httpx, aiohttp, urllib3, urllib, paramiko, smtplib, whatever the next addon imports. Unix sockets, loopback (IPv4-mapped `::ffff:127.0.0.1` too), `localhost` and every name under it, and the mail catcher always pass. PostgreSQL does too, because libpq connects in C. | `devguard.egress.enable`, `devguard.egress.allowHosts` |
| `mail` | Every SMTP connection lands on Mailpit, whatever `ir.mail_server` record, from-filter or API transport a mail names; TLS and authentication are faked; IMAP and POP3 are refused. | `devguard.mail.enable`; the catcher is the `mailpit` tree |
| `jobs` | Skips denylisted scheduled actions by exact external id, even when switched back on: `auto_backup`, currency rates, online bank statements, EDI output, the mail gateway, publisher notifications and web push. Its log lines read `odoo_devguard[crons]`. | `devguard.jobs.enable`, `devguard.jobs.extraBlocked` |
| `objectstore` | `fs.storage` records can only be local (`file`, `odoofs`, `memory`). An S3 or SFTP storage cannot be opened, so attachments and backups cannot reach a production bucket. | `devguard.objectstore.enable` |
| `backups` | `auto_backup` jobs to SFTP or an FS Storage are skipped, and so is their retention pass, which would delete production's backups. | `devguard.backups.enable` |
| `webhooks`, `iap` | Outbound webhook actions do nothing; IAP calls fail with a readable error. | `devguard.webhooks.enable`, `devguard.iap.enable` |

Only `egress` and the mail transport are transport-level: they know nothing about Odoo, so they hold across upgrades and unknown addons. The others patch Odoo and addon APIs so that a refusal reads as "Blocked by odoo-devguard" instead of a socket error, which also makes them one refactor away from being bypassed. A patch target that has moved fails the import loudly (`DevGuardPatchError`) rather than leaving an inert guard.

Treat it as a large reduction in blast radius plus an egress firewall for the Odoo process, not an airgap for the machine.

## Letting something through

Each guard announces itself on first use and names what it blocked:

```text
WARNING odoo_devguard[egress] ACTIVE -- outbound connections from this process are refused (loopback only). Allow a destination with devguard.egress.allowHosts, ...
```

For one command:

```bash
ODOO_DEVGUARD_EGRESS_ALLOW_HOSTS=api.example.com,10.0.0.0/8 odoo shell   # these destinations
ODOO_DEVGUARD_DISABLE=jobs odoo db migrate                               # named guards off
ODOO_DEVGUARD_ENABLED=0 odoo …                                           # everything off
```

Or permanently, with `devguard.egress.allowHosts`: hostnames (`*.example.com` for subdomains), IP literals or CIDRs. The environment variable replaces that list for the command rather than adding to it. A hostname is matched against the name a connection was resolved from, since clients resolve a name and then connect to the address, and a refusal names that host: `blocked connection to 104.16.246.239:443 (api-sandbox.gocardless.com)`. An address that an allowed name shares with another host, as on a CDN, passes for both.

Settings are baked into the environment from Nix and read at run time. `ODOO_DEVGUARD_<GUARD>_<KEY>` variables win; below them, a runtime file (`$ODOO_DEVGUARD_RUNTIME`, else `$DEVENV_RUNTIME/devguard-runtime.json`, JSON in the baked shape) changes a setting for a running shell without a rebuild.

The guard core is shared with frappe-nix (python-devops-nix's `lib.devguard`); odoo-nix supplies the Odoo-facing guards.

## Mail

Open Mailpit at the address the banner prints (`mailpit.httpPort`). Mailpit runs whether or not the mail guard is on: with the guard off, a database's own `ir.mail_server` records decide where mail goes. The shell warns when the mail guard is on and `mailpit.enable` is off, because mail would then be redirected to a port where nothing listens.

## Restores need the guard

`devguard.enable = false` is a decision about the whole project, not one command, so `odoo db restore` and `odoo project restore` refuse to run while it is off. `ODOO_NIX_RESTORE_ALLOW_UNGUARDED=1` overrides that for one command, and `restore.requireDevguard = false` for the project. See [Restore a production backup](restore-from-production.md).

## Older names

`devguard.crons.*` is now `devguard.jobs.*`, and `mailcatch.*` is now `devguard.mail.enable` and `mailpit.*`. The old options, `ODOO_DEVGUARD_DISABLE=crons` and the `ODOO_DEVGUARD_CRONS_*` variables still work with a warning through 1.x. The `dev_mailcatch` addon is a no-op stub kept through 1.x so an old `server_wide_modules` still starts; remove it from any you set by hand. `ODOO_MAILCATCH_*` and the `[dev_mailcatch]` section are gone. See [Upgrading odoo-nix](upgrading.md#renamed-options).
