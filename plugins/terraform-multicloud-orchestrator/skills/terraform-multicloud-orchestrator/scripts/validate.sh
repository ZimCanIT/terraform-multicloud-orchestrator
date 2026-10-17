#!/usr/bin/env bash
set -euo pipefail

# Usage: validate.sh [--static | --plan] [PLAN_OUT] [JSON_OUT]
#   --static  init -backend=false, validate, fmt -check. Needs no state or credentials.
#   --plan    init, plan, show -json, then list the resources the plan deletes or replaces.
#   (none)    both, in that order.
MODE="all"
case "${1:-}" in
  --static | --plan)
    MODE="${1#--}"
    shift
    ;;
  -*)
    echo "Usage: validate.sh [--static | --plan] [PLAN_OUT] [JSON_OUT]" >&2
    exit 2
    ;;
esac

PLAN_OUT="${1:-tfplan}"
JSON_OUT="${2:-plan_output.json}"

if [[ -n "${TERRAFORM_BIN:-}" ]]; then
  TF_BIN="${TERRAFORM_BIN}"
elif command -v terraform > /dev/null 2>&1; then
  TF_BIN="terraform"
elif command -v tofu > /dev/null 2>&1; then
  TF_BIN="tofu"
else
  echo "Error: terraform or tofu must be installed and available on PATH." >&2
  exit 127
fi

echo "Using ${TF_BIN}"

if [[ "${MODE}" != "plan" ]]; then
  "${TF_BIN}" init -backend=false -input=false
  "${TF_BIN}" validate
  "${TF_BIN}" fmt -check
fi

if [[ "${MODE}" != "static" ]]; then
  if ! command -v jq > /dev/null 2>&1; then
    echo "Error: jq must be installed and available on PATH to list deleted or replaced resources." >&2
    exit 127
  fi

  # Reads real state, so it needs backend access and credentials. A plan made
  # without state can only show creates and says nothing about replacement.
  "${TF_BIN}" init -input=false
  "${TF_BIN}" plan -input=false -out="${PLAN_OUT}"
  "${TF_BIN}" show -json "${PLAN_OUT}" > "${JSON_OUT}"

  echo "Plan written to ${PLAN_OUT}"
  echo "Plan JSON written to ${JSON_OUT}"
  echo "Resources the plan deletes or replaces (none listed means none):"
  jq -r '.resource_changes[]? | select(.change.actions | index("delete")) | "\(.address)\t\(.change.actions | join("+"))"' "${JSON_OUT}"
fi
