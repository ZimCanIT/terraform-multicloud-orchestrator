# Eval workspace fixtures

Synthetic Terraform configurations for `tests/test_grade_eval_workspaces.py`. Each
directory stands in for the working directory that `claude plugin eval --keep-temp`
leaves behind. They use only the built-in `terraform_data` resource, so
`terraform init` needs no provider download.

| Directory | What it is |
| --- | --- |
| `good` | Valid and formatted. |
| `unsupported-argument` | Valid syntax, but `terraform validate` rejects an argument. |
| `syntax-error` | An unterminated string. |
| `unformatted` | Valid, but `terraform fmt -check` reports a difference. |
| `with-module` | A root that calls a local module. |
