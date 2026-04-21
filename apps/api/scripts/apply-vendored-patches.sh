#!/usr/bin/env bash
# apps/api/scripts/apply-vendored-patches.sh
#
# Idempotent re-application of patches living in scripts/vendored_patches/
# on top of the verbatim tree under
# apps/api/src/insightxpert_api/vendored/agents_core/.
#
# Each patch is generated with `diff -u` from inside the agents_core directory
# (paths in the hunk headers are plain filenames), so we apply with `patch -p0`
# from that directory.
#
# Idempotency: we try a dry-run first; if the patch reports already-applied or
# doesn't apply cleanly, we skip rather than error out.

set -euo pipefail

cd "$(dirname "$0")/.."  # apps/api
VENDORED="src/insightxpert_api/vendored/agents_core"

shopt -s nullglob
patches=(scripts/vendored_patches/*.patch)
if [[ ${#patches[@]} -eq 0 ]]; then
  echo "no patches to apply"
  exit 0
fi

for patch in "${patches[@]}"; do
  name="$(basename "$patch")"
  # -N prevents `patch` from auto-reversing an already-applied patch on dry-run,
  # which is exactly how we detect "already applied" in idempotency checks.
  if patch -p0 -N --dry-run --silent -d "$VENDORED" <"$patch" >/dev/null 2>&1; then
    echo "applying $name"
    patch -p0 -N -d "$VENDORED" <"$patch" >/dev/null
  else
    # Confirm reverse-applies cleanly => already applied. Otherwise flag.
    if patch -p0 -R --dry-run --silent -d "$VENDORED" <"$patch" >/dev/null 2>&1; then
      echo "skipping $name (already applied)"
    else
      echo "skipping $name (does not apply cleanly; manual review needed)" >&2
    fi
  fi
done
