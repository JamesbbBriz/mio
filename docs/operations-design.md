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

## Explicit disk-analyzer trash (0.4.x)

Single-click selects a genuine scan entry; double-click or row activation enters a directory. The always-visible “删除所选…” control above the map explains missing selection or incomplete scanning when clicked. Execution still refuses partial scans, incomplete entries, and synthetic aggregate tiles; the control is disabled during scanning or mutation. It never targets the scan root implicitly. Confirmation shows the exact path, file/folder type, checked item count and logical size. Directories are moved as a whole, including their contents.

`disk_operations.py` builds an immutable descriptor-based snapshot bounded to 20,000 entries, depth 128 and 30 seconds per validation pass. It rejects home/ancestor/system root containers, the system trash tree, symlinks, special files, hard-linked regular files, different owners, device boundaries, unreadable items and live/unknown open-handle probes. Confirmation execution repeats this validation, compares every descendant signature and parent identity, then rebinds the parent and target immediately before GIO trash. A fresh plan is required after any change. There is no permanent-delete fallback and no privilege escalation. The GIO call has the existing 30-second cancellable budget; cancellation before the sink refuses mutation.

Navigation and selection are held while reviewing/moving; cancelling the dialog releases them. Only a confirmed successful GIO return triggers the targeted character slash. The old map stays briefly as an animation receipt, then the complete cached tree is invalidated and the current directory rescanned. Failure leaves the map visible with an error and no success animation; success does not claim freed space. Reduced-motion mode refreshes immediately with a static receipt.

Review: followed the bugs skill's discovery → bounds/ownership/open handles → fresh plan → parent/target rebind → GIO-only sink → accounting path. Directory snapshots cannot atomically lock an entire tree against another application: descendant changes or opens after the final check remain a concurrency limitation. Keep recovery available and close relevant applications before confirming. Tests cover changed descendants, replacements, links/special files, limits/cancellation, busy and protected targets, false sink returns, private-session real file/directory trash and restore, and native UI cancel/failure/success/target-animation/rescan. No real user files are used.

## Context actions and navigation

Disk tiles and right-hand list rows offer “移入系统回收站…” on right-click. A right-click selects the clicked genuine scan entry and opens a menu only; the action calls the same `review_disk_delete` plan/confirmation flow as the toolbar. Partial scans and synthetic aggregates remain refused. The list handles native `row-activated` for double-click/keyboard directory navigation; single-click selects, and regular files are not opened or deleted by activation. Map primary and secondary gestures use distinct buttons.

Cache rows offer “清理此项缓存…” for that exact group, independent of other checked groups. The toolbar “清理所选缓存…” still uses all checked groups. Both call the existing bounded cache planner, show the exact file list and require confirmation; successful moves trigger the existing slash receipt. Menus are dismissed on scan/reflow, and callbacks reject a replaced scan. No extra mutation sink is introduced. Disk refusals now name the encountered path and distinguish symbolic links, hard links and special files, without weakening refusal.

Entry-point review: checked 3 new context entry points / defective 0 after verification / not applicable 0. GUI fixtures exercise right-click selection, partial-scan refusal, review cancellation, sink failure, success animation, and list activation; the refusal-diagnostic regression failed against the old generic message before passing with specific paths/types. All operations in these checks use temporary fixtures.


## Memory diagnosis and reviewed process exit

`processes.py` reads bounded `/proc` metadata off the GTK thread, with at most 4096 PIDs and a four-second sampling budget. RSS, optional top-process PSS, swap and PSI have explicit units; missing permissions or vanished processes are counted. The nearest cgroup unit distinguishes managed services from ordinary app scopes beneath user@UID.service. Snapshots retain only the preceding sample and evidence for surviving process identities; no process history or command-line arguments are persisted.

An observed orphan requires unchanged child PID/start ticks, a changed parent, and evidence that the previously observed parent exited (including a zombie or reused parent PID). Absence from an incomplete PID enumeration or a permission-denied parent is not death evidence. First-seen init/systemd adoption is only suspected, not proof of uselessness. Managed services remain read-only even when their parent-exit observation is retained. Sampling cannot recover exits before monitoring or all short-lived transitions. Zombies have already exited and cannot be terminated again to reclaim RAM.

`process_actions.py` is the only new mutation sink. The review lists exact identities and executable paths, warns about unsaved work, and freezes the selection. Up to 64 same-user processes are allowed; privileged users, services, desktop/session components, Mio/ancestors/descendants, zombies and incomplete identities are refused. Every target is pinned with pidfd, then all targets are revalidated before any signal; each is revalidated again immediately before SIGTERM. PID/start ticks, all four UIDs, executable path/inode and cgroup must match review. Cancellation prevents later sends. No raw PID kill, process-group signal, sudo, SIGKILL, cache-dropping or swap manipulation is exposed. Unsupported pidfd fails closed.

The entire batch waits at most three seconds for pidfd readability and reports confirmed exit separately from request-only/refusal. It never claims RSS was freed or that sending a signal means success. The GUI refreshes memory after completion. A live process can exec or change relationships after the final metadata check; pidfd prevents signalling a different PID generation but cannot freeze the same process's program. SIGTERM may lose unsaved work or be ignored, and service restarts are not claimed as permanent exits.

Review using the repository bugs skill: checked 2 new action entry paths (individual selection, program-group selection) / defective 0 after verification / not applicable 1 (automatic orphan killing is not exposed). Tests exercise malformed/parenthesized stat names, normal daemon/service separation, missing permissions, PID reuse, incomplete samples, real parent exit with subreaper adoption, identity rebinding, batch-wide preflight, cancellation, ignored termination, and real pidfd termination of an owned fixture only. CI fixture cgroup placement is represented as an app scope only for that owned target; real PID/start/UID/executable and signalling remain exercised. Native tests verify evidence filters, confirmation cancel, stale identity, and exit versus pending receipts.

Reference semantics: [Linux /proc](https://www.kernel.org/doc/html/latest/filesystems/proc.html), [PSI](https://www.kernel.org/doc/html/latest/accounting/psi.html), [subreaper adoption](https://man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html), [pidfd signalling](https://man7.org/linux/man-pages/man2/pidfd_send_signal.2.html).
