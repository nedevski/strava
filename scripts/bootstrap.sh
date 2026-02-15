#!/usr/bin/env bash
set -Eeuo pipefail

DEFAULT_UPSTREAM_REPO="${GIT_SWEATY_UPSTREAM_REPO:-aspain/git-sweaty}"
SETUP_SCRIPT_REL="scripts/setup_auth.py"

info() {
  printf '%s\n' "$*"
}

warn() {
  printf 'WARN: %s\n' "$*" >&2
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

expand_path() {
  local path="$1"
  if [[ "$path" == "~" ]]; then
    printf '%s\n' "$HOME"
    return 0
  fi
  if [[ "$path" == ~/* ]]; then
    printf '%s/%s\n' "$HOME" "${path#~/}"
    return 0
  fi
  printf '%s\n' "$path"
}

is_compatible_clone() {
  local repo_dir="$1"
  [[ -e "$repo_dir/.git" && -f "$repo_dir/$SETUP_SCRIPT_REL" ]] || return 1
  git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1
}

prompt_yes_no() {
  local prompt="$1"
  local default="${2:-Y}"
  local suffix="[y/n] (default: n)"
  local answer

  if [[ "$default" == "Y" ]]; then
    suffix="[y/n] (default: y)"
  fi

  while true; do
    read -r -p "$prompt $suffix " answer || return 1
    answer="$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')"
    case "$answer" in
      "")
        [[ "$default" == "Y" ]] && return 0 || return 1
        ;;
      y|yes) return 0 ;;
      n|no) return 1 ;;
      *) info "Please enter y or n." ;;
    esac
  done
}

require_cmd() {
  have_cmd "$1" || fail "Missing required command: $1"
}

gh_is_authenticated() {
  gh auth status >/dev/null 2>&1
}

ensure_gh_auth() {
  require_cmd gh
  if gh_is_authenticated; then
    return 0
  fi

  info "GitHub CLI is not authenticated."
  if prompt_yes_no "Run gh auth login now?" "Y"; then
    gh auth login
  fi

  gh_is_authenticated || fail "GitHub CLI auth is required. Run 'gh auth login' and re-run bootstrap."
}

repo_name_from_slug() {
  local slug="$1"
  printf '%s\n' "${slug##*/}"
}

detect_local_repo_root() {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 1
  fi

  local root
  root="$(git rev-parse --show-toplevel)"
  if [[ -f "$root/$SETUP_SCRIPT_REL" ]]; then
    printf '%s\n' "$root"
    return 0
  fi
  return 1
}

ensure_repo_dir_ready() {
  local repo_dir="$1"
  if is_compatible_clone "$repo_dir"; then
    return 0
  fi
  if [[ -e "$repo_dir" ]]; then
    fail "Path already exists and is not a compatible clone: $repo_dir"
  fi
}

prompt_existing_clone_path() {
  local default_repo_dir="$1"
  local raw repo_dir

  printf '\n' >&2
  printf 'Default clone directory is: %s\n' "$default_repo_dir" >&2
  printf 'Choose this for a fresh setup, or point to an existing compatible clone.\n' >&2
  if ! prompt_yes_no "Use an existing local clone path?" "N"; then
    return 1
  fi

  while true; do
    read -r -p "Existing clone path (press Enter to cancel): " raw || return 1
    raw="$(printf '%s' "$raw" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    if [[ -z "$raw" ]]; then
      return 1
    fi

    repo_dir="$(expand_path "$raw")"
    if is_compatible_clone "$repo_dir"; then
      printf '%s\n' "$repo_dir"
      return 0
    fi

    warn "Not a compatible clone: $repo_dir"
    warn "Expected both: $repo_dir/.git and $repo_dir/$SETUP_SCRIPT_REL"
  done
}

configure_fork_remotes() {
  local repo_dir="$1"
  local upstream_repo="$2"
  local fork_repo="$3"

  git -C "$repo_dir" remote set-url origin "https://github.com/${fork_repo}.git"
  if git -C "$repo_dir" remote get-url upstream >/dev/null 2>&1; then
    git -C "$repo_dir" remote set-url upstream "https://github.com/${upstream_repo}.git"
  else
    git -C "$repo_dir" remote add upstream "https://github.com/${upstream_repo}.git"
  fi
}

fork_and_clone() {
  local upstream_repo="$1"
  local repo_dir="$2"
  local login fork_repo

  ensure_gh_auth

  login="$(gh api user --jq .login 2>/dev/null || true)"
  [[ -n "$login" ]] || fail "Unable to resolve GitHub username from current gh auth session."
  fork_repo="${login}/$(repo_name_from_slug "$upstream_repo")"

  info "Ensuring fork exists: $fork_repo"
  if ! gh repo fork "$upstream_repo" --clone=false --remote=false >/dev/null 2>&1; then
    warn "Fork creation command did not succeed cleanly. Continuing if fork already exists."
  fi
  gh repo view "$fork_repo" >/dev/null 2>&1 || fail "Fork is not accessible: $fork_repo"

  if is_compatible_clone "$repo_dir"; then
    info "Using existing clone at $repo_dir"
  else
    ensure_repo_dir_ready "$repo_dir"
    info "Cloning fork into $repo_dir"
    git clone "https://github.com/${fork_repo}.git" "$repo_dir"
  fi

  configure_fork_remotes "$repo_dir" "$upstream_repo" "$fork_repo"
}

clone_upstream() {
  local upstream_repo="$1"
  local repo_dir="$2"

  if is_compatible_clone "$repo_dir"; then
    info "Using existing clone at $repo_dir"
    return 0
  fi

  ensure_repo_dir_ready "$repo_dir"
  info "Cloning upstream repository into $repo_dir"
  git clone "https://github.com/${upstream_repo}.git" "$repo_dir"
}

run_setup() {
  local repo_root="$1"
  shift || true

  [[ -f "$repo_root/$SETUP_SCRIPT_REL" ]] || fail "Missing setup script: $repo_root/$SETUP_SCRIPT_REL"
  ensure_gh_auth
  require_cmd python3

  info ""
  info "Launching setup script..."
  (cd "$repo_root" && python3 "$SETUP_SCRIPT_REL" "$@")
}

main() {
  local upstream_repo="$DEFAULT_UPSTREAM_REPO"
  local repo_dir local_root existing_clone_path

  require_cmd git
  require_cmd python3

  if local_root="$(detect_local_repo_root)"; then
    info "Detected local clone: $local_root"
    if prompt_yes_no "Run setup now?" "Y"; then
      run_setup "$local_root" "$@"
    else
      info "Skipped setup. Run this when ready:"
      info "  (cd \"$local_root\" && ./scripts/bootstrap.sh)"
    fi
    return 0
  fi

  repo_dir="$(pwd)/$(repo_name_from_slug "$upstream_repo")"
  info "No compatible local clone detected in current working tree."
  info "Upstream repository: $upstream_repo"
  info "Target clone directory: $repo_dir"
  if existing_clone_path="$(prompt_existing_clone_path "$repo_dir")"; then
    repo_dir="$existing_clone_path"
    info "Using existing clone at $repo_dir"
    if prompt_yes_no "Run setup now?" "Y"; then
      run_setup "$repo_dir" "$@"
    else
      info "Setup not run. Next step:"
      info "  (cd \"$repo_dir\" && ./scripts/bootstrap.sh)"
    fi
    return 0
  fi

  if prompt_yes_no "Fork the repo to your GitHub account first?" "Y"; then
    fork_and_clone "$upstream_repo" "$repo_dir"
  else
    if ! prompt_yes_no "Clone upstream directly (without forking)?" "Y"; then
      info "No repository action selected. Exiting."
      return 0
    fi
    clone_upstream "$upstream_repo" "$repo_dir"
  fi

  if prompt_yes_no "Run setup now?" "Y"; then
    run_setup "$repo_dir" "$@"
  else
    info "Setup not run. Next step:"
    info "  (cd \"$repo_dir\" && ./scripts/bootstrap.sh)"
  fi
}

main "$@"
