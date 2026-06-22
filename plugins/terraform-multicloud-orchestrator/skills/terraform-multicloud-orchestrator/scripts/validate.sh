#!/usr/bin/env bash
set -euo pipefail

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
"${TF_BIN}" init -backend=false -input=false
"${TF_BIN}" validate
"${TF_BIN}" fmt -check
"${TF_BIN}" plan -input=false -out="${PLAN_OUT}"
"${TF_BIN}" show -json "${PLAN_OUT}" > "${JSON_OUT}"

echo "Plan written to ${PLAN_OUT}"
echo "Plan JSON written to ${JSON_OUT}"
