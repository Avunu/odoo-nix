# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Carbon Backend Theme",
    "summary": "IBM Carbon Design System theme for the Odoo backend",
    "version": "18.0.1.0.0",
    "category": "Themes/Backend",
    "author": "Avunu LLC",
    "website": "https://github.com/Avunu/web_theme_carbon",
    # AGPL-3 is inherited from web_dark_mode (AGPL-3).
    # web_responsive is LGPL-3 and does not itself force this.
    "license": "AGPL-3",
    "depends": ["web", "web_responsive", "web_dark_mode"],
    "installable": True,
    "data": [
        "views/res_company_views.xml",
        "views/webclient_templates.xml",
    ],
    "application": False,
    # After web_responsive (1) and web_dark_mode so our assets sort last.
    "sequence": 3,
    "assets": {
        # ------------------------------------------------------------------
        # Private sub-bundle: the compile-time variable layer.
        #
        # Declared here rather than in web._assets_primary_variables on
        # purpose. That bundle is reached by web.assets_frontend (through
        # web._assets_helpers) AND by web.report_assets_common, so a
        # ('prepend', ...) there would repaint the website and every PDF
        # report in Carbon too. Anchoring with ('before', ...) from inside
        # a backend bundle keeps the blast radius to the backend.
        #
        # This resolves because AssetPaths.index() (ir_asset.py) searches the
        # whole flattened list: by the time our commands run, the includes
        # have already spliced the anchor into it.
        # ------------------------------------------------------------------
        "web_theme_carbon._variables": [
            (
                "before",
                "web/static/src/scss/primary_variables.scss",
                "web_theme_carbon/static/src/scss/generated/_carbon_tokens.scss",
            ),
            (
                "before",
                "web/static/src/scss/primary_variables.scss",
                "web_theme_carbon/static/src/scss/bridge/primary_variables.scss",
            ),
            # Lands after every *.variables.scss and secondary_variables.scss,
            # which is the only way to reach the vars Odoo declares without
            # !default, plus the raw Bootstrap $vars.
            (
                "before",
                "web/static/src/scss/bootstrap_overridden.scss",
                "web_theme_carbon/static/src/scss/bridge/late.scss",
            ),
        ],
        "web_theme_carbon._variables_dark": [
            (
                "before",
                "web/static/src/scss/primary_variables.scss",
                "web_theme_carbon/static/src/scss/generated/_carbon_tokens_dark.scss",
            ),
            (
                "before",
                "web/static/src/scss/primary_variables.scss",
                "web_theme_carbon/static/src/scss/bridge_dark/primary_variables.scss",
            ),
            (
                "before",
                "web/static/src/scss/bootstrap_overridden.scss",
                "web_theme_carbon/static/src/scss/bridge_dark/late.scss",
            ),
        ],
        # ----------------------------------------------------------- LIGHT
        "web.assets_backend": [
            ("include", "web_theme_carbon._variables"),
            # Kept out of static/lib/carbon/*.css and components/*.scss on
            # purpose: neither print-bundle remove glob matches it, so IBM Plex
            # survives on paper while the colour layer does not.
            "web_theme_carbon/static/src/scss/generated/_carbon_fonts.scss",
            "web_theme_carbon/static/lib/carbon/carbon.g10.css",
            "web_theme_carbon/static/src/scss/components/*.scss",
            # Behaviour, not just styling. Two Carbon patterns Odoo has no
            # equivalent for: the UI Shell's global search (which opens Odoo's
            # own command palette) and the data-table toolbar search.
            "web_theme_carbon/static/src/js/**/*.js",
            "web_theme_carbon/static/src/js/**/*.xml",
        ],
        # graph/pivot re-include _assets_helpers, so they get their own
        # variable pass; without this they stay Odoo-purple.
        "web.assets_backend_lazy": [
            ("include", "web_theme_carbon._variables"),
        ],
        # ------------------------------------------------------------ DARK
        # assets_web_dark = include(assets_web) + web's *.dark.scss, so
        # everything above is already in the list here. SCSS variables must
        # therefore go in via ('before', ...) at the front, while custom
        # properties win by being appended at the back. Same bundle, opposite
        # ends -- that asymmetry is the whole dark-mode mechanism.
        "web.assets_web_dark": [
            ("include", "web_theme_carbon._variables_dark"),
            "web_theme_carbon/static/lib/carbon/carbon.g100.css",
        ],
        "web.assets_backend_lazy_dark": [
            ("include", "web_theme_carbon._variables_dark"),
        ],
        # ----------------------------------------------------------- PRINT
        # assets_web_print includes assets_backend, so the whole visual layer
        # lands on paper. g10's #f4f4f4 canvas and layer-accent table headers
        # are not printing colours -- primary_variables_print.scss exists
        # precisely to avoid that, and it wins on the VARIABLES because it
        # loads before our bridge and our bridge is all !default. The runtime
        # token CSS and the component rules are not variables, though, so they
        # have to be dropped explicitly.
        #
        # BOTH entries are globs on purpose. _get_paths() returns a truthy
        # placeholder for an unresolved NON-wildcard path, so a bare path that
        # stops resolving makes AssetPaths.remove() raise ValueError and 500s
        # every backend page. A glob that matches nothing returns [] and is a
        # safe no-op.
        "web.assets_web_print": [
            ("remove", "web_theme_carbon/static/lib/carbon/*.css"),
            ("remove", "web_theme_carbon/static/src/scss/components/*.scss"),
        ],
    },
}
