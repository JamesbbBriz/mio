# Mio development guide

This fork adds an independent native Linux GUI to Mole CLI's repository. Use Mio / 澪 as the public application name. The personal repository is `JamesbbBriz/mio`.

- `mio_linux/backend.py`: read-only Linux adapters and descriptor-based filesystem scanning.
- `mio_linux/treemap.py`: GTK-independent, area-preserving layout.
- `mio_linux/disk_view.py`: native interactive treemap.
- `mio_linux/app.py`: GTK 4 / libadwaita frontend. Keep scanning off the main thread.
- `assets/`: original Mio mascot and icon; see `docs/branding.md`.
- `tests/test_backend.py`, `tests/test_treemap.py`, `tests/smoke_gui.py`: isolated Linux checks.

Run `python3 -m unittest discover -s tests -p 'test_*.py' -v` and the GUI smoke test after substantive GUI changes. GUI tests use temporary fixtures. In headless CI use Xvfb, `GSETTINGS_BACKEND=memory`, and `GSK_RENDERER=cairo`.

Keep symlink refusal, filesystem boundaries, bounded scans, cancellation, and honest partial-result reporting. Logical size is not reclaimable space. Current GUI operations are read-only; deletion and uninstallation require a separately reviewed recovery and privilege design. Never test destructive operations against real user data.

Upstream shell and Go code remains a macOS CLI. Its safety documentation, copyright, and GPL-3.0 license still apply to changes in those components. Do not imply that the proprietary Mac GUI is open source or that Mio is an official Mole product. Preserve upstream Git history; do not rewrite published tags.
