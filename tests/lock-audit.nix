# The stale-lock audit (python-devops-nix's lib.python.lockAudit, wired in
# lib/python.nix) against tests/fixtures/stale-lock: 18.0's fixture after a
# module was added to the install set without re-locking. uv2nix alone would
# build the environment without it; the audit names it and fails evaluation.
# Pure evaluation, so { name = { expected; actual; }; } for mkEvalCheck.
{
  pkgs,
  lib,
  inputs,
  python,
}:
let
  envs = import ../lib/python.nix {
    inherit pkgs lib python;
    workspaceRoot = ./fixtures/stale-lock;
    projectName = "odoo-nix-stale-lock";
    coreSource = inputs.ocb-18;
    inherit (inputs) pyproject-nix pyproject-build-systems uv2nix;
    pythonLib = inputs.python-devops-nix.lib.python;
  };
  inherit (envs.lockAudit) missing message;

  evaluates = env: (builtins.tryEval env.drvPath).success;
in
{
  lock-audit-missing = {
    expected = [
      {
        where = "pyproject.toml";
        req = "odoo-addon-queue_job";
        name = "odoo-addon-queue-job";
      }
    ];
    actual = missing;
  };

  # The lines of the message a user acts on: what is missing, and the fix.
  # Lists the ones the message lacks.
  lock-audit-message = {
    expected = [ ];
    actual = lib.filter (line: !lib.hasInfix line message) [
      "odoo-nix: uv.lock does not cover every declared dependency"
      "pyproject.toml requires odoo-addon-queue_job, but 'odoo-addon-queue-job' is not in uv.lock"
      "a module added to modules.txt"
      "    uv lock\n"
    ];
  };

  # Every virtualenv goes through it: none evaluates.
  lock-audit-throws = {
    expected = {
      odooPythonEnv = false;
      devPythonEnv = false;
      testPythonEnv = false;
    };
    actual = {
      odooPythonEnv = evaluates envs.odooPythonEnv;
      devPythonEnv = evaluates envs.devPythonEnv;
      testPythonEnv = evaluates envs.testPythonEnv;
    };
  };
}
