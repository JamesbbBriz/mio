# Upstream and provenance

Mio is an independent fork of [tw93/Mole](https://github.com/tw93/Mole), created through GitHub's fork feature. The initial upstream base is `122bf83cb433a5e194a7af62ee9fb4c78ef3cc26` (Mole CLI V1.61.0). Upstream history, copyright notices, and GPL-3.0 license are retained.

The Linux GUI lives in `mio_linux/`, with its own read-only filesystem adapters, GTK frontend, native treemap, tests, launcher, and original character assets. It does not call the macOS cleanup scripts. Upstream shell / Go CLI sources remain available for reference and future carefully scoped adaptation.

The native Mole Mac GUI is a separate proprietary product. This fork does not include that GUI's source, images, logos, or private rule catalogs. No native GUI reverse engineering has been completed. REA is an optional future research tool, not a runtime dependency.

Mio uses an independent name and icon in accordance with the upstream [trademark policy](https://github.com/tw93/Mole/blob/main/TRADEMARK.md). Mio is not endorsed by or affiliated with Mole.

The root README and contribution guide describe Mio. The original CLI documentation remains in upstream Git history and in the unchanged translated readmes. Use the upstream repository for current macOS CLI instructions.

Inherited macOS / release / scheduled workflows are archived in `docs/upstream/workflows/`. The active workflow is `.github/workflows/mio.yml`, which checks the Linux GUI without publishing binaries.

Only source code is published at this stage. There is no official Mio binary distribution or package release yet.
