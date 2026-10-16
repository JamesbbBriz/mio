# Mio operation design and review

The GUI runs as the user. File recovery and privileged package operations are separate domains.

## Cache cleanup and system trash (0.3.1)

Users select cache groups and review exact regular files older than seven days. The bounded descriptor scanner excludes links, special files, hard links, other owners and incomplete trees. Final metadata, parent identity and open-handle checks remain before mutation. GIO File.trash then owns trash placement, volume rules and standard freedesktop metadata. There is no permanent-delete or copy/delete fallback when trashing fails.

Mio exposes only an “Open system trash” shortcut, launching trash:/// in the default file manager. It has no duplicate trash list, restore controls or permanent-delete controls. GNOME Files owns those user interactions and the system trash state. An independent GIO consumer in the tests emulates file-manager restore/delete to verify interoperability; that consumer is not shipped as a product page.

Filesystem/GVfs APIs do not provide an atomic compare-and-move across independent applications. Final validation narrows but cannot eliminate a concurrent namespace replacement; a process may also open a cache file after the probe. Close relevant apps and retain recovery until reviewed. GIO cancellation has a 30-second operation budget; batch cancellation stops later items. Failures and timeouts never trigger raw deletion or success accounting.

Legacy recovery.py remains only for old records and isolated regression coverage. Migration is explicitly reviewed: restore to the recorded original location without overwrite, then system-trash it so original-path metadata is correct. A conflict leaves the legacy item intact. If step two fails or is interrupted, the file remains at its original location; report that location. No automatic migration of unknown data occurs.

Real interoperability tests use a private HOME, XDG_DATA_HOME and D-Bus session. They cover Mio-to-system visibility, system-to-Mio restore, restore conflicts, nonempty directories, link deletion without target deletion, externally restored stale selections, repeated restore/re-trash and legacy migration. No user's real trash is emptied or changed for testing.

## Packages and maintenance

Inventory uses dpkg-query, snap list and flatpak list with exact IDs and installation scope. No arbitrary command text or shell interpolation is accepted. APT removal is simulated before review. The actual manager runs interactively in a desktop terminal with sudo where needed; its fresh dependency list and confirmation remain authoritative. No automatic yes, force, purge, autoremove or inferred application-data cleanup accompanies uninstall. Snap's normal snapshot behavior is retained. Flatpak keeps application data.

Maintenance exposes fixed commands for package index refresh, upgrade, package consistency checking, APT archive cleanup and journal retention. The latter two are explicitly irreversible. Transactions are delegated to the manager and are not killed by a GUI close or a generic timeout. Read-only probes have bounded timeouts. A runner writes a completion record with the actual exit status; starting a terminal is never reported as success. Interrupted runners remain unknown, not successful.

## Review (2026-10-17)

Design self-review against the repository bugs skill (updated for 0.3.1): distinct review and execution; no deletion from partial scans; rebind at final file sink; no overwrite during restore; GIO-owned volume routing; cancellation stops subsequent items; counts include only completed moves; exact package IDs; manager-owned dependency and privilege decisions. No host cleanup or uninstall is used for testing. The remaining concurrency boundary is an application opening an eligible file after the open-handle probe; recovery is retained until separately removed. No Mac CLI changes are involved.

Mutation-family review: checked 2 (system trash handoff, legacy migration) / defects found after verification 0 / not applicable 2 (restore and erase now belong to the file manager). Sources: https://docs.gtk.org/gio/method.File.trash.html and https://specifications.freedesktop.org/trash/1.0/.
