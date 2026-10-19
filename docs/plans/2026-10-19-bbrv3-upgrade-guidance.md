# BBRv3 upgrade guidance implementation plan

**Goal:** Keep the default installation on the existing kernel, explain the optional BBRv3 benefits and upgrade cost, and allow Ubuntu 24.04+ / Debian 12+ for explicit kernel upgrades.

**Architecture:** Reuse the separate `bbrv3 --tag ... --yes` command and its existing package, boot and rollback checks. Share numeric release checks between the main platform gate and kernel preflight; retain Ubuntu 22.04 for ordinary tools only. Show a noninteractive hint after an installation without failures, except when `--skip-bbr` is requested. No remote upstream installer is executed.

**Tech Stack:** Bash, Python standard-library unittest, existing ShellCheck/Zsh checks.

1. Update `tests/test_platform.py` to cover minimum/newer releases, both architectures, malformed/old/other distributions, and the real kernel preflight with boot/system boundaries mocked. Add isolated CLI tests for successful/skipped/failed BBR, default installation without kernel changes, and explicit upgrade gating. Run the focused tests and confirm new expectations fail before implementation.
2. Update `lib/common.sh` and `modules/kernel.sh` to use numeric minimum versions; keep tag, architecture, container, GRUB, free-space and Secure Boot checks. Update `install.sh` and the hint in `modules/kernel.sh` without adding interactive prompts, kernel changes or reboot to default installation.
3. Update `README.md`, `agent.md` and `docs/verification.md` with support ranges, conditional benefits, two-stage workflow, version selection, restart/verification and actual local test results. Reference Google's BBRv3 overview for performance claims.
4. Run `python3 -m unittest discover -s tests -v`, `bash tests/check.sh` and `git diff --check`. Review the final diff and record any unavailable checks. Local mocks do not establish real kernel boot or rollback readiness. Leave changes uncommitted for user review.

**Completed validation:** All 78 behavioral tests passed with no skips. The repository check script passed using ShellCheck 0.11.0 temporarily supplied from `/private/tmp`, including Bash/Zsh syntax and Git whitespace/ignore checks. CLI `--help` passed. No server changes, kernel installation/reboot, CI run, Git commit or push were performed; real kernel boot and rollback still require Linux validation.
