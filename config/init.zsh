# ShellReady interactive configuration. No effect on non-interactive scripts.
[[ -o interactive ]] || return
[[ -n ${_SHELLREADY_LOADED:-} ]] && return
typeset -g _SHELLREADY_LOADED=1
typeset -g SHELLREADY_HOME="$HOME/.local/share/shellready"
typeset -U path
path=("$SHELLREADY_HOME/bin" $path)
HISTFILE=${HISTFILE:-$HOME/.zsh_history}
HISTSIZE=50000
SAVEHIST=50000
setopt APPEND_HISTORY INC_APPEND_HISTORY HIST_IGNORE_DUPS HIST_IGNORE_SPACE
autoload -Uz compinit
compinit
if [[ -r "$SHELLREADY_HOME/bin/zsh-autosuggestions.zsh" ]]; then
    source "$SHELLREADY_HOME/bin/zsh-autosuggestions.zsh"
fi
if [[ -x "$SHELLREADY_HOME/bin/zoxide" ]]; then
    eval "$("$SHELLREADY_HOME/bin/zoxide" init zsh)"
fi
if [[ -x "$SHELLREADY_HOME/bin/atuin" ]]; then
    export ATUIN_CONFIG_DIR="$SHELLREADY_HOME/config/atuin"
    eval "$("$SHELLREADY_HOME/bin/atuin" init zsh --disable-up-arrow --disable-ai)"
fi
if [[ -x "$SHELLREADY_HOME/bin/starship" ]]; then
    export STARSHIP_CONFIG="$SHELLREADY_HOME/config/starship.toml"
    eval "$("$SHELLREADY_HOME/bin/starship" init zsh)"
fi
