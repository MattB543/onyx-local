#!/bin/sh
#
# install-git-hooks.sh — install the fork's versioned pre-push hook
# (scripts/git-hooks/pre-push) into this clone. Run from any checkout:
#
#   sh scripts/install-git-hooks.sh [--force]
#
# The installed hook is a small shim that runs the versioned copy from the
# checkout being pushed, so hook changes on main apply without a reinstall.
# Git for Windows runs hooks with its bundled sh, so this also works there.
# --force replaces an existing hook that is not a shim (the old one is kept
# as pre-push.bak).

set -eu

force=0
[ "${1:-}" = "--force" ] && force=1

hooks_dir=$(git rev-parse --path-format=absolute --git-path hooks)
target="$hooks_dir/pre-push"
marker="installed by scripts/install-git-hooks.sh"
mkdir -p "$hooks_dir"

if [ -e "$target" ] && ! grep -q "$marker" "$target"; then
  if [ "$force" = 0 ]; then
    echo "$target already exists and is not a shim. Re-run with --force to replace it." >&2
    exit 1
  fi
  mv "$target" "$target.bak"
  echo "Moved the old pre-push hook to $target.bak"
fi

cat >"$target" <<'EOF'
#!/bin/sh
# installed by scripts/install-git-hooks.sh. Runs the versioned hook from this checkout.
hook="$(git rev-parse --show-toplevel)/scripts/git-hooks/pre-push"
if [ -f "$hook" ]; then
  exec sh "$hook" "$@"
fi
echo "pre-push: $hook not found in this checkout; hook skipped."
EOF
chmod +x "$target"
echo "Installed $target"
