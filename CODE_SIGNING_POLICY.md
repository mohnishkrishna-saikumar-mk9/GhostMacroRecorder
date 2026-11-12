# Code signing policy

> **Status:** applying to [SignPath Foundation](https://signpath.org) for free code signing.
> Once approved, Windows releases will carry this attribution:
>
> **Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).**

## What gets signed

| Artifact | Platform | Signed |
| --- | --- | --- |
| `GhostMacroRecorder-Setup.exe` (installer) | Windows 10/11 x64 | Yes, once approved |
| `GhostMacroRecorder.exe` (installed app) | Windows 10/11 x64 | Yes, once approved |

Only binaries built from this repository are signed. Nothing built elsewhere is signed under this project.

## How releases are built

Every release is built from the public source in this repository by GitHub Actions
([`.github/workflows/release.yml`](.github/workflows/release.yml)):

1. Pushing a version tag (`v*`) starts the workflow on a GitHub-hosted Windows runner.
2. It installs the pinned dependencies from [`requirements.txt`](requirements.txt), runs the test suite,
   builds the app with PyInstaller and the installer with Inno Setup.
3. The unsigned installer is submitted to SignPath for signing. A project approver manually approves
   each signing request.
4. The signed installer is attached to the GitHub Release.

Releases are published only on the
[GitHub Releases page](https://github.com/mohnishkrishna-saikumar-mk9/GhostMacroRecorder/releases).
Downloads are free.

## Team and roles

| Role | Members |
| --- | --- |
| Committers and reviewers | [@mohnishkrishna-saikumar-mk9](https://github.com/mohnishkrishna-saikumar-mk9) |
| Approvers | [@mohnishkrishna-saikumar-mk9](https://github.com/mohnishkrishna-saikumar-mk9) |

- **Committers** may change the source directly.
- **Reviewers** review every change from outside contributors (pull requests) before it is merged.
- **Approvers** approve every signing request.

All team members use multi-factor authentication for GitHub and SignPath.

## Privacy policy

This program will not transfer any information to other networked systems unless specifically
requested by the user or the person installing or operating it.

Ghost Macro Recorder works fully offline. It has no network code, analytics or telemetry. Settings and
saved macros are stored only on your own PC in `%APPDATA%\GhostMacroRecorder`. See [SECURITY.md](SECURITY.md).

## Uninstalling

The installer registers a standard uninstaller: *Settings → Apps → Installed apps → Ghost Macro Recorder → Uninstall*.
It also removes the optional "Start with Windows" entry.

## Reporting a problem

If you believe a signed release of this project violates this policy, open an issue or contact the
maintainer through GitHub. Violations of SignPath Foundation's terms can be reported to support@signpath.io.
