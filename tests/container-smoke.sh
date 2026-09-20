#!/usr/bin/env bash
# Run only inside a disposable Debian/Ubuntu container, never on a workstation.
set -euo pipefail
[[ -f /.dockerenv ]] || { echo 'This test requires a disposable Docker container' >&2; exit 1; }
cd /src
useradd -m -s /bin/bash smoke
printf 'echo preserved\n' > /home/smoke/.zshrc
printf 'echo history-before-install\n' > /home/smoke/.bash_history
chown smoke:smoke /home/smoke/.zshrc /home/smoke/.bash_history
before=$(uname -r)
bash install.sh install --user smoke --skip-bbr
bash install.sh install --user smoke --skip-bbr
[[ $(getent passwd smoke | cut -d: -f7) == /bin/zsh ]] || exit 1
[[ $(grep -c '^# >>> ShellReady >>>$' /home/smoke/.zshrc) == 1 ]] || exit 1
[[ $(uname -r) == "$before" ]] || exit 1
[[ ! -f /etc/sysctl.d/90-shellready-bbr.conf ]] || exit 1
[[ $(stat -c %U /home/smoke/.zshrc) == smoke ]] || exit 1
# Variables intentionally expand in the target user Zsh.
# shellcheck disable=SC2016
runuser -u smoke -- env HOME=/home/smoke zsh -elic '
  [[ -n $_SHELLREADY_LOADED ]] || exit 1
  trz --version
  tsz --version
  starship --version
  atuin --version
  zoxide --version
  atuin search --cmd-only history-before-install | grep history-before-install
  mkdir -p "$HOME/visit-this-directory"
  cd "$HOME/visit-this-directory"
  zoxide add "$PWD"
  zoxide query visit-this-directory
'
# Explicitly avoid root's HOME even when configuring a user via sudo conventions.
SUDO_USER=smoke bash install.sh uninstall
[[ $(getent passwd smoke | cut -d: -f7) == /bin/bash ]] || exit 1
[[ ! -e /home/smoke/.local/share/shellready ]] || exit 1
grep -q 'echo preserved' /home/smoke/.zshrc
[[ -s /home/smoke/.local/share/atuin/history.db ]] || exit 1
[[ -d /home/smoke/.local/state/shellready/backups ]] || exit 1
# Root user path and keep-shell are separate supported flows.
bash install.sh install --user root --keep-shell --skip-bbr
bash install.sh uninstall --user root
