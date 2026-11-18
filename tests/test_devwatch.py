"""odoo_devwatch (lib/devwatch/odoo_devwatch) without Odoo: the pattern parsing,
the matching, and the watcher filter against a stand-in `odoo.service.server`
shaped like OCB's (FSWatcherWatchdog and FSWatcherInotify, each reading
odoo.addons.__path__ in its constructor and scheduling what it sees).

Checked: the explicit list drops a root whatever it holds; the covered list
drops a root only where its links reach code another watched root covers,
keeps it with a warning otherwise, and drops dangling links; an excluded root
never reaches the watcher; every root is back on odoo.addons.__path__
afterwards, including when the constructor raises; install() is inert with no
patterns; the patch applies once; a namespace path (Odoo 19 and master) is
filtered and restored the same way.

Run: python3 tests/test_devwatch.py <dir holding odoo_devwatch>
     The directory must be the grafted package: mkGraft writes _hook.py beside
     __init__.py, which the repo tree does not have (checks.devwatch).
"""

import os
import sys
import tempfile
import types
import unittest

if len(sys.argv) < 2:
    sys.exit("usage: test_devwatch.py <dir holding odoo_devwatch>")
PARENT = os.path.abspath(sys.argv.pop(1))
sys.path.insert(0, PARENT)

import odoo_devwatch

EXCLUDE = odoo_devwatch.EXCLUDE_ENV
COVERED = odoo_devwatch.COVERED_ENV

BUILD = "/src/modules/web/web_dialog_size/build/__editable__/odoo/addons"
WEB_RESPONSIVE = "/src/modules/web/web_responsive/build/__editable__/odoo/addons"
VENDOR = "/src/vendor/extra"
ROOTS = [
    "/src/odoo/odoo/addons",
    "/src/modules/web",
    BUILD,
    WEB_RESPONSIVE,
    "/src/custom",
]
DEFAULT_COVERED = ("*/build/__editable__/*",)


def install_fake_odoo():
    """A stand-in odoo.addons and odoo.service.server in sys.modules."""
    odoo = types.ModuleType("odoo")
    addons = types.ModuleType("odoo.addons")
    addons.__path__ = list(ROOTS)
    service = types.ModuleType("odoo.service")
    server = types.ModuleType("odoo.service.server")
    odoo.addons, odoo.service = addons, service
    service.server = server
    sys.modules.update(
        {
            "odoo": odoo,
            "odoo.addons": addons,
            "odoo.service": service,
            "odoo.service.server": server,
        }
    )
    return addons, server


ODOO_MODULES = ("odoo", "odoo.addons", "odoo.service", "odoo.service.server")


def isolate_odoo_modules(case):
    """Put back whatever odoo modules were in sys.modules once the test is done."""
    saved = {name: sys.modules.get(name) for name in ODOO_MODULES}

    def restore():
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    case.addCleanup(restore)


def make_watcher(name, log, fail=False):
    """A watcher class in the shape of OCB's: it reads odoo.addons.__path__
    in __init__ and schedules each entry, recording what it was shown."""

    class Watcher:
        def __init__(self):
            import odoo.addons

            self.seen = list(odoo.addons.__path__)
            self.scheduled = []
            for path in odoo.addons.__path__:
                self.scheduled.append(path)
            log.append((name, self.seen))
            if fail:
                raise RuntimeError("boom")

    Watcher.__name__ = name
    return Watcher


class PatternTests(unittest.TestCase):
    def test_unset_and_empty_mean_no_patterns(self):
        self.assertEqual(odoo_devwatch.patterns(EXCLUDE, {}), ())
        self.assertEqual(odoo_devwatch.patterns(EXCLUDE, {EXCLUDE: ""}), ())
        self.assertEqual(odoo_devwatch.patterns(EXCLUDE, {EXCLUDE: ":"}), ())

    def test_colon_separated_and_empty_entries_dropped(self):
        pats = odoo_devwatch.patterns(EXCLUDE, {EXCLUDE: "*/a/*::*/b/*:"})
        self.assertEqual(pats, ("*/a/*", "*/b/*"))

    def test_whitespace_around_entries_is_stripped(self):
        environ = {EXCLUDE: " */a/* : */b/* ", COVERED: "   "}
        self.assertEqual(odoo_devwatch.patterns(EXCLUDE, environ), ("*/a/*", "*/b/*"))
        self.assertEqual(odoo_devwatch.patterns(COVERED, environ), ())

    def test_each_variable_is_read_on_its_own(self):
        environ = {EXCLUDE: "*/a/*", COVERED: "*/b/*"}
        self.assertEqual(odoo_devwatch.patterns(EXCLUDE, environ), ("*/a/*",))
        self.assertEqual(odoo_devwatch.patterns(COVERED, environ), ("*/b/*",))

    def test_default_covered_pattern_matches_editable_trees_only(self):
        self.assertTrue(odoo_devwatch.excluded(BUILD, DEFAULT_COVERED))
        self.assertFalse(odoo_devwatch.excluded("/src/modules/web", DEFAULT_COVERED))
        self.assertFalse(odoo_devwatch.excluded("/src/custom", DEFAULT_COVERED))

    def test_star_crosses_slashes_and_match_is_case_sensitive(self):
        self.assertTrue(odoo_devwatch.excluded("/a/b/c/d", ("/a/*/d",)))
        self.assertFalse(odoo_devwatch.excluded("/A/b", ("/a/*",)))


class WatcherFilterTests(unittest.TestCase):
    def setUp(self):
        isolate_odoo_modules(self)
        self.addons, self.server = install_fake_odoo()
        self.log = []
        self.server.FSWatcherWatchdog = make_watcher("FSWatcherWatchdog", self.log)
        self.server.FSWatcherInotify = make_watcher("FSWatcherInotify", self.log)

    def test_covered_roots_do_not_reach_the_watcher(self):
        odoo_devwatch.patch_server(self.server, covered=DEFAULT_COVERED)
        self.server.FSWatcherWatchdog()
        name, seen = self.log[-1]
        self.assertEqual(name, "FSWatcherWatchdog")
        self.assertNotIn(BUILD, seen)
        self.assertNotIn(WEB_RESPONSIVE, seen)
        self.assertIn("/src/modules/web", seen)
        self.assertIn("/src/custom", seen)

    def test_explicit_roots_are_dropped_whatever_they_hold(self):
        # The explicit list drops the root. VENDOR does not exist here, so there
        # is no code to warn about; LinkCoverTests covers real code and the warning.
        self.addons.__path__.append(VENDOR)
        odoo_devwatch.patch_server(self.server, explicit=("*/vendor/*",))
        with self.assertNoLogs("odoo.service.server", level="WARNING"):
            self.server.FSWatcherWatchdog()
        self.assertNotIn(VENDOR, self.log[-1][1])
        self.assertIn(VENDOR, self.addons.__path__)

    def test_explicit_list_wins_over_the_covered_list(self):
        odoo_devwatch.patch_server(
            self.server, explicit=("*/build/__editable__/*",), covered=("*",)
        )
        self.server.FSWatcherWatchdog()
        self.assertNotIn(BUILD, self.log[-1][1])

    def test_import_path_is_restored_after_construction(self):
        before = list(self.addons.__path__)
        identity = self.addons.__path__
        odoo_devwatch.patch_server(self.server, covered=DEFAULT_COVERED)
        self.server.FSWatcherWatchdog()
        self.assertEqual(self.addons.__path__, before)
        self.assertIs(self.addons.__path__, identity)

    def test_import_path_is_restored_when_the_constructor_raises(self):
        before = list(self.addons.__path__)
        self.server.FSWatcherWatchdog = make_watcher(
            "FSWatcherWatchdog", self.log, fail=True
        )
        odoo_devwatch.patch_server(self.server, covered=DEFAULT_COVERED)
        with self.assertRaises(RuntimeError):
            self.server.FSWatcherWatchdog()
        self.assertEqual(self.addons.__path__, before)

    def test_inotify_watcher_is_filtered_too(self):
        odoo_devwatch.patch_server(self.server, covered=DEFAULT_COVERED)
        self.server.FSWatcherInotify()
        name, seen = self.log[-1]
        self.assertEqual(name, "FSWatcherInotify")
        self.assertNotIn(BUILD, seen)

    def test_patch_applies_once(self):
        odoo_devwatch.patch_server(self.server, covered=DEFAULT_COVERED)
        first = self.server.FSWatcherWatchdog.__init__
        odoo_devwatch.patch_server(self.server, covered=DEFAULT_COVERED)
        self.assertIs(self.server.FSWatcherWatchdog.__init__, first)
        self.server.FSWatcherWatchdog()
        self.assertEqual(len(self.log), 1)

    def test_missing_watcher_class_is_skipped(self):
        del self.server.FSWatcherInotify
        odoo_devwatch.patch_server(self.server, covered=DEFAULT_COVERED)
        self.server.FSWatcherWatchdog()
        self.assertNotIn(BUILD, self.log[-1][1])

    def test_a_server_with_no_watcher_class_says_the_filter_is_idle(self):
        del self.server.FSWatcherWatchdog
        del self.server.FSWatcherInotify
        with self.assertLogs("odoo.service.server", level="WARNING") as logs:
            odoo_devwatch.patch_server(self.server, covered=DEFAULT_COVERED)
        self.assertIn("have no effect", logs.output[0])

    def test_install_arms_for_either_variable_and_is_inert_for_neither(self):
        calls = []
        real = odoo_devwatch.on_import
        saved_flag = odoo_devwatch._INSTALLED
        saved_env = {k: os.environ.pop(k, None) for k in (EXCLUDE, COVERED)}
        try:

            def reset(**env):
                for key in (EXCLUDE, COVERED):
                    os.environ.pop(key, None)
                os.environ.update(env)
                odoo_devwatch._INSTALLED = False
                calls.clear()
                odoo_devwatch.install()
                return list(calls)

            odoo_devwatch.on_import = lambda name, cb: calls.append(name)
            self.assertEqual(reset(), [])
            self.assertEqual(reset(**{EXCLUDE: "*/vendor/*"}), ["odoo.service.server"])
            self.assertEqual(
                reset(**{COVERED: "*/build/__editable__/*"}), ["odoo.service.server"]
            )
        finally:
            odoo_devwatch.on_import = real
            odoo_devwatch._INSTALLED = saved_flag
            for key, value in saved_env.items():
                os.environ.pop(key, None)
                if value is not None:
                    os.environ[key] = value


class LinkCoverTests(unittest.TestCase):
    """A covered root is dropped only when the code its links reach stays watched."""

    def setUp(self):
        isolate_odoo_modules(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = os.path.realpath(tmp.name)
        self.src = os.path.join(base, "src", "web")  # a watched root
        self.module = os.path.join(self.src, "mod_a")  # its module code
        self.elsewhere = os.path.join(base, "elsewhere", "mod_b")  # under no root
        os.makedirs(self.module)
        os.makedirs(self.elsewhere)
        self.covered = self.build_root(base, "covered", "mod_a", self.module)
        self.outside = self.build_root(base, "outside", "mod_b", self.elsewhere)
        self.dangling = self.build_root(
            base, "dangling", "gone", os.path.join(base, "nowhere")
        )
        self.addons, self.server = install_fake_odoo()
        self.log = []
        self.server.FSWatcherWatchdog = make_watcher("FSWatcherWatchdog", self.log)
        self.addons.__path__[:] = [self.src, self.covered, self.outside, self.dangling]
        odoo_devwatch.patch_server(self.server, covered=DEFAULT_COVERED)

    @staticmethod
    def build_root(base, repo, name, target):
        root = os.path.join(base, repo, "build", "__editable__", "odoo", "addons")
        os.makedirs(root)
        os.symlink(target, os.path.join(root, name))
        return root

    def watched(self):
        """What the watcher is shown; the fixture's uncovered root always warns."""
        with self.assertLogs("odoo.service.server", level="WARNING") as logs:
            self.server.FSWatcherWatchdog()
        self.warnings = logs.output
        return self.log[-1][1]

    def test_links_into_a_watched_root_are_dropped(self):
        self.assertNotIn(self.covered, self.watched())

    def test_dangling_links_are_dropped(self):
        self.assertNotIn(self.dangling, self.watched())

    def test_links_outside_every_watched_root_keep_the_root_and_warn(self):
        self.assertIn(self.outside, self.watched())
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("not watched through any other root", self.warnings[0])

    def test_the_import_path_keeps_every_root_through_the_cover_check(self):
        self.watched()
        self.assertEqual(
            self.addons.__path__, [self.src, self.covered, self.outside, self.dangling]
        )

    def test_a_real_directory_is_not_a_link_into_watched_code(self):
        # The root holds code of its own, not a link: nothing watches it.
        base = os.path.dirname(os.path.dirname(self.src))
        root = os.path.join(base, "realrepo", "build", "__editable__", "odoo", "addons")
        os.makedirs(os.path.join(root, "real_mod"))
        self.addons.__path__.append(root)
        self.assertIn(root, self.watched())

    def test_a_prefix_sibling_of_a_watched_root_is_not_covered(self):
        sibling = self.src + "x"  # .../src/webx, a sibling of .../src/web
        os.makedirs(os.path.join(sibling, "mod_c"))
        base = os.path.dirname(os.path.dirname(self.src))
        sibling_root = self.build_root(
            base, "sibling", "mod_c", os.path.join(sibling, "mod_c")
        )
        self.addons.__path__.append(sibling_root)
        self.assertIn(sibling_root, self.watched())

    def test_an_empty_root_has_nothing_to_lose(self):
        base = os.path.dirname(os.path.dirname(self.src))
        empty = os.path.join(base, "empty", "build", "__editable__", "odoo", "addons")
        os.makedirs(empty)
        self.addons.__path__.append(empty)
        self.assertNotIn(empty, self.watched())

    def test_a_nonexistent_root_has_nothing_to_lose(self):
        base = os.path.dirname(os.path.dirname(self.src))
        ghost = os.path.join(base, "ghost", "build", "__editable__", "odoo", "addons")
        self.addons.__path__.append(ghost)
        self.assertNotIn(ghost, self.watched())

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0, "root reads anything"
    )
    def test_an_unreadable_root_is_kept_not_assumed_covered(self):
        base = os.path.dirname(os.path.dirname(self.src))
        locked = self.build_root(base, "locked", "x", self.module)
        os.chmod(locked, 0o000)
        self.addCleanup(os.chmod, locked, 0o755)
        self.addons.__path__.append(locked)
        self.assertIn(locked, self.watched())

    def test_an_explicit_exclusion_of_uncovered_code_is_dropped_and_warns(self):
        cls = make_watcher("FSWatcherWatchdog", self.log)
        odoo_devwatch._wrap_init(cls, ("*/outside/*",), ())
        with self.assertLogs("odoo.service.server", level="WARNING") as logs:
            cls()
        self.assertNotIn(self.outside, self.log[-1][1])
        self.assertIn("will not reload", logs.output[0])

    def test_an_explicit_exclusion_of_covered_code_is_dropped_quietly(self):
        cls = make_watcher("FSWatcherWatchdog", self.log)
        odoo_devwatch._wrap_init(cls, ("*/covered/*",), ())
        with self.assertNoLogs("odoo.service.server", level="WARNING"):
            cls()
        self.assertNotIn(self.covered, self.log[-1][1])


class NamespacePathTests(unittest.TestCase):
    """Odoo 19 and master: odoo.addons.__path__ is a _NamespacePath, frozen."""

    def setUp(self):
        isolate_odoo_modules(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = os.path.realpath(tmp.name)
        self.keep = os.path.join(base, "keep", "fakens_devwatch")
        self.drop = os.path.join(base, "drop", "fakens_devwatch")
        os.makedirs(self.keep)
        os.makedirs(self.drop)
        sys.path[:0] = [os.path.dirname(self.keep), os.path.dirname(self.drop)]
        self.addCleanup(sys.path.remove, os.path.dirname(self.keep))
        self.addCleanup(sys.path.remove, os.path.dirname(self.drop))
        self.addCleanup(sys.modules.pop, "fakens_devwatch", None)
        import fakens_devwatch

        self.ns = fakens_devwatch.__path__
        self.ns._path_finder = lambda *a: None  # as Odoo 19 and master freeze it
        self.log = []
        self.addons, self.server = install_fake_odoo()
        self.addons.__path__ = self.ns
        self.server.FSWatcherWatchdog = make_watcher("FSWatcherWatchdog", self.log)

    def test_a_namespace_path_is_filtered_for_the_watcher_and_restored(self):
        before = list(self.ns)
        self.assertEqual(len(before), 2)
        odoo_devwatch.patch_server(self.server, explicit=("*/drop/*",))
        self.server.FSWatcherWatchdog()
        self.assertEqual(self.log[-1][1], [self.keep])
        self.assertEqual(list(self.ns), before)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1], verbosity=2)
