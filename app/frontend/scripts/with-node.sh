#!/bin/sh
set -eu
component_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$component_root"
# Task runners do not load interactive shell setup. Select the project's
# installed nvm version explicitly, or use Homebrew's versioned Node.
if [ -d "/opt/homebrew/opt/node@24/bin" ]; then
    PATH="/opt/homebrew/opt/node@24/bin:$PATH"
    export PATH
elif [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    # dash ignores arguments passed to dot; a function provides portable $@.
    load_nvm() { . "$NVM_DIR/nvm.sh"; }
    load_nvm --no-use
    # Resolve the installed version without changing npm's global prefix.
    # `nvm use` rejects user prefixes, even though local app commands work.
    node_binary=$(nvm which "$(cat "$component_root/.nvmrc")")
    PATH="$(dirname "$node_binary"):$PATH"
    export PATH
fi
if ! command -v node >/dev/null 2>&1 || [ "$(node -p 'process.versions.node.split(".")[0]')" != "24" ]; then
    echo "Node 24 is required. Install it with 'nvm install 24' or add it to PATH." >&2
    exit 1
fi
exec "$@"
