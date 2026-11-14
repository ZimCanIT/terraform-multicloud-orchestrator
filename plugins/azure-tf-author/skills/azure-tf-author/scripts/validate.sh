#!/usr/bin/env bash
# Plan-only validation chain for humans and CI. It never runs apply or destroy.
#
# Usage: validate.sh [--static | --plan] [--fail-on-delete] [--keep-json] [PLAN_OUT]
#   --static           init -backend=false, validate, fmt -check -diff. Reads no state and needs
#                      no backend credentials, but does need network access to download providers.
#   --plan             init, plan -out=PLAN_OUT, show -json, then list the resources the plan
#                      deletes or replaces. Reads real state, so it needs backend access and credentials.
#   (none)             runs --static, then --plan.
#   --fail-on-delete   exit 3 if the plan deletes or replaces any resource.
#   --keep-json        keep plan_output.json in the current directory. By default the JSON is a
#                      temporary file that is removed on exit.
#   PLAN_OUT           plan file (default: tfplan). It holds plan values in cleartext: keep it out of git.
set -euo pipefail

umask 077

MODE="all"
FAIL_ON_DELETE="false"
KEEP_JSON="false"
PLAN_OUT="tfplan"
PLAN_OUT_SET="false"

usage() {
  echo "Usage: validate.sh [--static | --plan] [--fail-on-delete] [--keep-json] [PLAN_OUT]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --static | --plan)
      if [[ "${MODE}" != "all" ]]; then
        echo "Error: choose one of --static or --plan." >&2
        usage
      fi
      MODE="${1#--}"
      ;;
    --fail-on-delete) FAIL_ON_DELETE="true" ;;
    --keep-json) KEEP_JSON="true" ;;
    -h | --help) usage ;;
    -*)
      echo "Error: unknown option: $1" >&2
      usage
      ;;
    *)
      if [[ "${PLAN_OUT_SET}" == "true" ]]; then
        echo "Error: unexpected extra argument: $1" >&2
        usage
      fi
      PLAN_OUT="$1"
      PLAN_OUT_SET="true"
      ;;
  esac
  shift
done

if ! compgen -G "*.tf" > /dev/null; then
  echo "Error: no *.tf files in $(pwd). Run this from a root module directory." >&2
  exit 2
fi

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

if [[ "${MODE}" != "static" ]] && ! command -v jq > /dev/null 2>&1; then
  echo "Error: jq must be installed to list deleted or replaced resources." >&2
  exit 127
fi

trap 'echo "Replacement check NOT performed: the run stopped before the check finished." >&2' ERR

export TF_IN_AUTOMATION=1
echo "Using ${TF_BIN}"

if [[ "${MODE}" != "plan" ]]; then
  "${TF_BIN}" init -backend=false -input=false -no-color
  "${TF_BIN}" validate -no-color
  "${TF_BIN}" fmt -check -recursive -diff
fi

if [[ "${MODE}" == "static" ]]; then
  echo "Replacement check NOT performed: static checks read no state, so they cannot see a replacement. Run --plan with backend access."
  exit 0
fi

JSON_OUT="plan_output.json"
if [[ "${KEEP_JSON}" != "true" ]]; then
  JSON_OUT="$(mktemp)"
  trap 'rm -f "${JSON_OUT}"' EXIT
fi

"${TF_BIN}" init -input=false -no-color
"${TF_BIN}" plan -input=false -no-color -out="${PLAN_OUT}"
"${TF_BIN}" show -json "${PLAN_OUT}" > "${JSON_OUT}"

DELETES="$(jq '[.resource_changes[]? | select(.change.actions | index("delete"))] | length' "${JSON_OUT}")"
echo "Plan written to ${PLAN_OUT}. It holds plan values in cleartext: keep it out of git."
if [[ "${KEEP_JSON}" == "true" ]]; then
  echo "Plan JSON written to ${JSON_OUT}. Keep it out of git."
fi
echo "Resources the plan deletes or replaces: ${DELETES} (none listed means none)"
jq -r 'limit(50; .resource_changes[]? | select(.change.actions | index("delete")) | "\(.address)\t\(.type)\t\(.change.actions | join("+"))\t\(.action_reason // .change.action_reason // "")")' "${JSON_OUT}"
if ((DELETES > 50)); then
  echo "List truncated: ${DELETES} resources in total; the first 50 are shown."
fi

if [[ "${FAIL_ON_DELETE}" == "true" && "${DELETES}" -gt 0 ]]; then
  echo "Stop: the plan deletes or replaces resources. Confirm each one before handoff." >&2
  exit 3
fi
