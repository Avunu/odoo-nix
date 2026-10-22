# Changelog

## [1.1.0](https://github.com/Avunu/odoo-nix/compare/v1.0.0...v1.1.0) (2026-10-22)


### Features

* **cli:** manage databases through odoo.modules.db as well as odoo.service.db ([ecd3c9b](https://github.com/Avunu/odoo-nix/commit/ecd3c9b7cfbe2258c327c1e4651404898971097d))
* **cli:** odoo project relock, and project update's relock and pull in Python ([06b155a](https://github.com/Avunu/odoo-nix/commit/06b155a4e182e4678896ad68cb0b934bd05ae868))
* **containers:** OCI labels and a healthcheck, opt-in &lt;name&gt;/odoo name and non-root user ([#81](https://github.com/Avunu/odoo-nix/issues/81)) ([4a9ae6a](https://github.com/Avunu/odoo-nix/commit/4a9ae6ab40358418a9e1521e41f86dd83db7a2aa))
* **init:** odoo-init in Python, with the shared scaffolder conventions ([5e6ae7a](https://github.com/Avunu/odoo-nix/commit/5e6ae7a6a8263ae4ddd3a166e1734b6ca9160013))
* **module:** odoo module remove, and module add and add-bundle in Python ([732aed3](https://github.com/Avunu/odoo-nix/commit/732aed351d0cabdef85926ef7b06b22e5f669d76))
* **nixos:** adopt python-devops-nix's production pieces (Phase 6) ([#73](https://github.com/Avunu/odoo-nix/issues/73)) ([4ecde4e](https://github.com/Avunu/odoo-nix/commit/4ecde4ef8e14bae38e9f2c59f1881cf26054ba20))
* support Odoo 20.0 ([aafa4ac](https://github.com/Avunu/odoo-nix/commit/aafa4acf58e720a7abb5cce44cd850d2ccfdafa9))


### Bug Fixes

* correct stale ports, bundle, migrate and without_demo texts ([80da220](https://github.com/Avunu/odoo-nix/commit/80da220710ea125036362afaa69e07b98cfc2a34))
* **deps:** bump devenv ([#86](https://github.com/Avunu/odoo-nix/issues/86)) ([29aa1e8](https://github.com/Avunu/odoo-nix/commit/29aa1e87415c13711bd43cbcab5865909016a4a8))

## 1.0.0 (2026-10-17)


### ⚠ BREAKING CHANGES

* **shell:** adopt the development shell option tree ([#58](https://github.com/Avunu/odoo-nix/issues/58))
* Track B renames: name, settings, ODOO_NIX_* variables ([#57](https://github.com/Avunu/odoo-nix/issues/57))

### Features

* add third-party git repos via odoo-add-module ([42ccd24](https://github.com/Avunu/odoo-nix/commit/42ccd243b56c9997de8a714403c25302bf759879))
* add third-party git repos via odoo-add-module ([bd4e206](https://github.com/Avunu/odoo-nix/commit/bd4e206759009872f98303b9ad00aac14cca4865))
* coreSource — OCB from a flake input instead of the odoo/ submodule ([3ef9519](https://github.com/Avunu/odoo-nix/commit/3ef951936bace89def3236702876847679f465d1))
* coreSource — OCB from a flake input instead of the odoo/ submodule ([8d2b117](https://github.com/Avunu/odoo-nix/commit/8d2b1177af92cc9d6aa54958752c15494ceebd01))
* demo data control switch ([3e05a97](https://github.com/Avunu/odoo-nix/commit/3e05a9747bc4c18be375827782376c8c7be6a6a5))
* **dev_mailcatch:** catch API-based mail transports; nginx body-size option ([2f9f676](https://github.com/Avunu/odoo-nix/commit/2f9f6760d1c8b74c79c07c7c65ed6a678923073d))
* **dev_mailcatch:** catch API-based mail transports; nginx body-size option ([67742f0](https://github.com/Avunu/odoo-nix/commit/67742f08ed7de5d5f4c6a0334927936e4cefa4b1))
* **devenv:** clone submodules as partial clones that can switch branches ([896d7ce](https://github.com/Avunu/odoo-nix/commit/896d7cea4105f15c7eb1243fb2579f48326f0154))
* **devguard:** adopt python-devops-nix's devguard core ([#56](https://github.com/Avunu/odoo-nix/issues/56)) ([3a1fb0f](https://github.com/Avunu/odoo-nix/commit/3a1fb0f9443fc91c2dff12e6aa678ff2bbb851f9))
* granular logging config ([1f4ef45](https://github.com/Avunu/odoo-nix/commit/1f4ef45e709dd76b42177e3626a1cad6b0576983))
* ide / vscode integration ([b4c4cef](https://github.com/Avunu/odoo-nix/commit/b4c4cef19bb627e92174c4a34949be10a65c4210))
* journald-native logging -- priorities, journal fields, JSON access log ([4dbeae2](https://github.com/Avunu/odoo-nix/commit/4dbeae2c4d5e60e467db7ab67541ab32249ee5aa))
* journald-native logging -- priorities, journal fields, JSON access log ([7196500](https://github.com/Avunu/odoo-nix/commit/7196500a51e01163d148fea5eb9e02cf8f6eb28a))
* mailcatch (mailpit integration) ([92c6128](https://github.com/Avunu/odoo-nix/commit/92c6128f8b4f6907fcacce1e8522318f74ac0b69))
* make browser tours actually run, and refuse to fake it when they cannot ([e4312ec](https://github.com/Avunu/odoo-nix/commit/e4312ec9ad341ce4a4af2d45575671b90a789bf5))
* manage custom postgres extensions ([4ce7f6f](https://github.com/Avunu/odoo-nix/commit/4ce7f6f3b134c6d43c8fc0a848c1116912cc9515))
* migrate the database on every start, updating only what changed ([b2d2373](https://github.com/Avunu/odoo-nix/commit/b2d2373af141e838333e24aa6286954f04429c11))
* migrate the database on every start, updating only what changed ([f25ac1d](https://github.com/Avunu/odoo-nix/commit/f25ac1dc6bb2b772eec354b4f4465abfa0514398))
* modules.txt sorter ([d7ccd34](https://github.com/Avunu/odoo-nix/commit/d7ccd34ac1215d1c5ba59e6ae157e76f0d628816))
* nix test suite against pinned OCB 18.0/19.0 inputs ([6b192b6](https://github.com/Avunu/odoo-nix/commit/6b192b6c56d58748d64e7d5c6b75d4c7e7ecf4a6))
* nix test suite against pinned OCB 18.0/19.0 inputs ([de3eb08](https://github.com/Avunu/odoo-nix/commit/de3eb08b42718edfce2446b4c4ecedfdfe972768))
* **nixos:** nginx.xSendfile serves filestore attachments from nginx ([#42](https://github.com/Avunu/odoo-nix/issues/42)) ([2547d4f](https://github.com/Avunu/odoo-nix/commit/2547d4f018d5b5ec1cb46b907414eb2474e4d8e1))
* OCA bundles ([fec0c06](https://github.com/Avunu/odoo-nix/commit/fec0c06c7a32fce9b99c16d55a30d6bdc2a77bd6))
* odoo language server ([fb5714e](https://github.com/Avunu/odoo-nix/commit/fb5714e4947d536409521aa61d09ba03df9fc35e))
* odoo project backup/restore, OCA auto_backup-compatible ([2864602](https://github.com/Avunu/odoo-nix/commit/2864602d37075a345a935db5d006d5798958b411))
* odoo project backup/restore, OCA auto_backup-compatible ([5a8a163](https://github.com/Avunu/odoo-nix/commit/5a8a16396d6385525f9ed76a45468344eccb4ade))
* odoo-migrate command ([848fae5](https://github.com/Avunu/odoo-nix/commit/848fae59e0eaeccce3a81e23ce6f045b5137bd9c))
* odoo-migrate command ([836f0d8](https://github.com/Avunu/odoo-nix/commit/836f0d89404c62a2a61d30603dccbcc25aa49f26))
* **python:** adopt python-devops-nix's Python environment pieces (Phase 4) ([#59](https://github.com/Avunu/odoo-nix/issues/59)) ([cd10f52](https://github.com/Avunu/odoo-nix/commit/cd10f52673d52e78ee05dd49d1e189755e49104b))
* pythonLibraries native libraries expose ([3ccc1bd](https://github.com/Avunu/odoo-nix/commit/3ccc1bd2e9087fb78336fb40c0c08639ba13e699))
* **release:** release odoo-nix with release-please and a release-1 branch ([#60](https://github.com/Avunu/odoo-nix/issues/60)) ([70b4a42](https://github.com/Avunu/odoo-nix/commit/70b4a42442643ae3304b9e20b7d957cf6c78ac68))
* **restore:** the restore conventions shared with frappe-nix ([#53](https://github.com/Avunu/odoo-nix/issues/53)) ([ca69c71](https://github.com/Avunu/odoo-nix/commit/ca69c71293450a1df85a6476ba96dc890435b8b5))
* **secrets:** adopt python-devops-nix's secrets toolkit and backup layer ([#52](https://github.com/Avunu/odoo-nix/issues/52)) ([510b0f1](https://github.com/Avunu/odoo-nix/commit/510b0f1a2c546be2e5affc11d61399f52ed4b6c2))
* **shell:** adopt python-devops-nix's development shell pieces (Phase 5) ([#62](https://github.com/Avunu/odoo-nix/issues/62)) ([51aad1e](https://github.com/Avunu/odoo-nix/commit/51aad1e851c1cb6d9a3484b809a5bbcd822eba96))
* **shell:** adopt the development shell option tree ([#58](https://github.com/Avunu/odoo-nix/issues/58)) ([f14b2db](https://github.com/Avunu/odoo-nix/commit/f14b2db2846058ea8964ceba8ed619664f64ecf9))
* Track B renames: name, settings, ODOO_NIX_* variables ([#57](https://github.com/Avunu/odoo-nix/issues/57)) ([dec0192](https://github.com/Avunu/odoo-nix/commit/dec019281587f3e58a10022321026c3e3637b9fa))
* unified `odoo` CLI for site maintenance (db/module/project) ([25f4a65](https://github.com/Avunu/odoo-nix/commit/25f4a65e49cd5c40d6915f8dd9dec02191f86c83))
* unified odoo CLI for site maintenance (db/module/project) ([7712dd4](https://github.com/Avunu/odoo-nix/commit/7712dd4059fb17af63db46a9c38f5e9e64a32ce4))


### Bug Fixes

* blas thread caps ([6f48132](https://github.com/Avunu/odoo-nix/commit/6f481325bc439980e48339d036ae3551f7bc9ba5))
* build lxml package overlay to resolve v18 python env error ([16296c0](https://github.com/Avunu/odoo-nix/commit/16296c0618982908cca767f5ef4bdace88a995c3))
* **containers:** prefix the image name with containers.registry ([#50](https://github.com/Avunu/odoo-nix/issues/50)) ([31075a7](https://github.com/Avunu/odoo-nix/commit/31075a78e922a59ffa629a4573491a11d36a0870))
* **deps:** bump the ocb group with 2 updates ([#63](https://github.com/Avunu/odoo-nix/issues/63)) ([2cf6a75](https://github.com/Avunu/odoo-nix/commit/2cf6a75032ca5bb998b5c1dd80c7ab88a8396f82))
* **devenv:** check out only submodules a clone has never had ([a834619](https://github.com/Avunu/odoo-nix/commit/a83461967cd57d823a70a9a1adeeb8d81c5faac2))
* **devenv:** don't force dotenv.enable under flake integration ([dea4f53](https://github.com/Avunu/odoo-nix/commit/dea4f53f653226d7c4a2c4dce99dc843ca343396))
* **devguard:** match egress hostname entries against what resolved ([#46](https://github.com/Avunu/odoo-nix/issues/46)) ([0b42a97](https://github.com/Avunu/odoo-nix/commit/0b42a97e9401afb44b7b3223f21c0bf72692a7d4))
* force update submodules to specified branches ([b084d71](https://github.com/Avunu/odoo-nix/commit/b084d71a88b3ed59c69e95c25a92ad3eccd5aa17))
* **lock:** move ocb-18 past a revision without pyproject.toml ([7381eb3](https://github.com/Avunu/odoo-nix/commit/7381eb33e81d82af11922891f2afc05594c3710d))
* **lock:** move ocb-19 past a revision without pyproject.toml ([e3f99d6](https://github.com/Avunu/odoo-nix/commit/e3f99d6f7d6f1b2700c231c0b1511f65be3e10f3))
* **module:** a database not named after the role is still owned by it ([3181cdf](https://github.com/Avunu/odoo-nix/commit/3181cdfb458385ba0466dc5623c0066af02ed08c))
* **module:** a database not named after the role is still owned by it ([0a6faab](https://github.com/Avunu/odoo-nix/commit/0a6faab5dfda841d11b7554916be632a226cf43a))
* **nixos:** keep backups and pre-migrate snapshots owner-only ([#51](https://github.com/Avunu/odoo-nix/issues/51)) ([8638f08](https://github.com/Avunu/odoo-nix/commit/8638f0889170a290661ed7fdcc7c154d6abea177))
* **nixos:** root `odoo` runs as the service; python-magic finds libmagic ([#40](https://github.com/Avunu/odoo-nix/issues/40)) ([024d871](https://github.com/Avunu/odoo-nix/commit/024d871bfcee04157a760198945dc891e2565bed))
* **oca_sources:** don't emit unpackaged modules as uv path sources ([#38](https://github.com/Avunu/odoo-nix/issues/38)) ([ec26c11](https://github.com/Avunu/odoo-nix/commit/ec26c11b502adc29fe868be88a721eaddbc6d14a))
* odoo CLI wrapper shadowed by OCB's own console script ([d0db2c1](https://github.com/Avunu/odoo-nix/commit/d0db2c18a26ab102be6af2c77050f3f80bc0f887))
* odoo CLI wrapper shadowed by OCB's own console script in dev shells ([d837b14](https://github.com/Avunu/odoo-nix/commit/d837b14a868117012680ffb4b1104d937403c837))
* series-derived python default, warning mailcatch aliases, real negative assertions ([#54](https://github.com/Avunu/odoo-nix/issues/54)) ([29417df](https://github.com/Avunu/odoo-nix/commit/29417dfbfb87a1b9319698cb5eca02b0b4a88323))
* silence docutils' unlogged RST noise during module update ([4b7f6fd](https://github.com/Avunu/odoo-nix/commit/4b7f6fddf321090788a39060f90e246ce3932ebd))
* silence docutils' unlogged RST noise during module update ([d5576da](https://github.com/Avunu/odoo-nix/commit/d5576da1a2ca326bf1b271822599314b399643e4))
* **submodules:** stop partial clones re-downloading history and piling up packs ([#39](https://github.com/Avunu/odoo-nix/issues/39)) ([bf7978b](https://github.com/Avunu/odoo-nix/commit/bf7978bf9a840e5111ef3df5544a0b414afe2c93))
* **tooling:** skip rich's racy test_brokenpipeerror ([#55](https://github.com/Avunu/odoo-nix/issues/55)) ([ae29436](https://github.com/Avunu/odoo-nix/commit/ae29436cd08449602f413ee0de0fdf0cb8d829c3))
* unscoped `git submodule update` silently reset other submodules ([349d144](https://github.com/Avunu/odoo-nix/commit/349d144826ced55911c5cf37d667355e11e4803a))
* unscoped git submodule update silently reset other submodules ([ed7a8fe](https://github.com/Avunu/odoo-nix/commit/ed7a8fe587555874f87ac4f965c0f444c732f25a))


### Performance Improvements

* **devenv:** first shell entry clones a submodule's paired branch only ([#45](https://github.com/Avunu/odoo-nix/issues/45)) ([a9e8f48](https://github.com/Avunu/odoo-nix/commit/a9e8f48d5ecd9678e46b548789e6f6ec0fd5cb8f))
* **devenv:** keep the dev PostgreSQL datadir off btrfs copy-on-write ([#41](https://github.com/Avunu/odoo-nix/issues/41)) ([19b78a5](https://github.com/Avunu/odoo-nix/commit/19b78a550392e843c5633b238baeca2e7b262285))
