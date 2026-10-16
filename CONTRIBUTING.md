# Contributing to Mio

Current work is in `mio_linux/`, `tests/test_backend.py`, `tests/test_treemap.py`, `tests/smoke_gui.py`, `assets/`, and `run.sh`. Install GTK 4, libadwaita, PyGObject, and Pycairo using the system package manager; see the README.

Run unit tests and the native GUI smoke test before submitting changes:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
GSETTINGS_BACKEND=memory python3 -m tests.smoke_gui
```

For headless environments:

```bash
GSETTINGS_BACKEND=memory GSK_RENDERER=cairo xvfb-run -a python3 -m tests.smoke_gui
```

Keep scanning off the UI thread. Preserve directory-descriptor traversal, symlink refusal, file-system boundaries, cancellation, and partial-result reporting. Do not describe logical file sizes as reclaimable space. Verify area preservation and keyboard / list navigation when changing the treemap.

Do not add destructive cleanup or package-uninstall actions without a separate reviewed design covering exact targets, user review, recovery, privilege boundaries, and fixture-based tests. Tests must not delete user files or invoke real administrator authorization.

Shell and Go files inherited from Mole are a separate macOS CLI surface. If changing them, follow their upstream safety design and relevant tests; GUI-only changes do not require unrelated destructive or macOS-only flows on Linux.

Code contributions are GPL-3.0. Respect upstream copyright and attribution, and use Mio's independent branding for this fork.
