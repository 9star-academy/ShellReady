#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
while IFS= read -r test_file; do
    if git check-ignore -q --no-index -- "$test_file"; then
        printf 'CI test file is ignored by Git: %s\n' "$test_file" >&2
        exit 1
    fi
done < <(find tests -type f \( -name '*.sh' -o -name '*.py' \))
while IFS= read -r script; do
    bash -n "$script"
done < <(find . -name '*.sh' -not -path './.git/*')
zsh -n config/init.zsh
shellcheck -x install.sh bootstrap.sh lib/*.sh modules/*.sh tests/*.sh
git diff --check
