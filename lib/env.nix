# Shared environment defaults for the Odoo process, applied identically by
# the devenv shell, the NixOS module, and the container image.

{
  # NumPy/SciPy/pandas/Bokeh/matplotlib (any of which an OCA module may pull
  # in transitively) auto-size their BLAS/OpenMP thread pools to the host's
  # CPU count the moment they're imported. Odoo is a request-serving app, not
  # a numeric workload, so that pool buys nothing -- it only spends real OS
  # threads on every import, and on a many-core box that thread-creation
  # burst can itself fail outright (observed: `OpenBLAS blas_thread_init:
  # pthread_create failed ... Resource temporarily unavailable` while loading
  # a module that depends on bokeh). Multi-worker prod/container deployments
  # make it worse: BLAS's thread pool does not survive os.fork() cleanly.
  # Capping every such library to 1 thread is the standard, always-safe fix.
  blasThreadCaps = {
    OPENBLAS_NUM_THREADS = "1";
    OMP_NUM_THREADS = "1";
    MKL_NUM_THREADS = "1";
    NUMEXPR_NUM_THREADS = "1";
  };
}
