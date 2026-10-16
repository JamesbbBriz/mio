# Mio operation design and review

The GUI runs as the user. File recovery and privileged package operations are separate domains.

## Cache cleanup and Mio recovery

Users select cache groups, then review an exact list of regular files older than seven days. A bounded descriptor scan refuses links, special files, hard links, other owners, other filesystems and incomplete trees. No application data/configuration paths are inferred from app names. Only explicitly selected files under the configured cache root are eligible. Active or unknown open-handle probes refuse the item. A final metadata and physical-parent recheck binds the move to the reviewed target. Linux renameat2(RENAME_NOREPLACE) avoids destination overwrite; no copy-and-delete fallback exists.

Each move has a durable intent record before its atomic rename into a private, same-filesystem Mio recovery store. An interrupted transaction is reconciled from the actual stored file; an intent without a file is not counted as moved. Recovery never overwrites a recreated original. It requires the original parent to exist with its recorded identity. Permanent removal is a separate explicit action on selected recovery records. Logical sizes are never advertised as reclaimed disk blocks; moving to recovery frees no space. The store is Mio-specific, not the desktop's freedesktop Trash.

A process may open or modify a file after the probe: no global application lock exists. Users must close relevant apps before cleanup. Unknown probe results refuse the operation; filesystem races cannot redirect operations through symlinks. Tests cover positive moves, restore conflicts, changed identity, links, cancellation and partial failure using disposable fixtures only.

## Packages and maintenance

Inventory uses dpkg-query, snap list and flatpak list with exact IDs and installation scope. No arbitrary command text or shell interpolation is accepted. APT removal is simulated before review. The actual manager runs interactively in a desktop terminal with sudo where needed; its fresh dependency list and confirmation remain authoritative. No automatic yes, force, purge, autoremove or inferred application-data cleanup accompanies uninstall. Snap's normal snapshot behavior is retained. Flatpak keeps application data.

Maintenance exposes fixed commands for package index refresh, upgrade, package consistency checking, APT archive cleanup and journal retention. The latter two are explicitly irreversible. Transactions are delegated to the manager and are not killed by a GUI close or a generic timeout. Read-only probes have bounded timeouts. A runner writes a completion record with the actual exit status; starting a terminal is never reported as success. Interrupted runners remain unknown, not successful.

## Review (2026-10-17)

Design self-review against the repository bugs skill: distinct review and execution; no deletion from partial scans; rebind at final file sink; no overwrite during restore; same-volume rename only; cancellation stops subsequent items; counts include only completed moves; exact package IDs; manager-owned dependency and privilege decisions. No host cleanup or uninstall is used for testing. The remaining concurrency boundary is an application opening an eligible file after the open-handle probe; recovery is retained until separately removed. No Mac CLI changes are involved.
