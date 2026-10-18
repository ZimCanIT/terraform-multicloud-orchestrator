# Security Policy

## Reporting a vulnerability

Report suspected vulnerabilities privately with GitHub private vulnerability reporting on this repository. Open the **Security** tab and choose **Report a vulnerability**.

Do not open a public issue or pull request for a vulnerability. Include the affected file or workflow, the steps to reproduce, and the impact you expect.

## Sensitive files

Plan files can hold secret values, so treat them as sensitive:

- `tfplan` and `plan_output.json` can contain secret values in cleartext. Keep them out of git, issues, pull requests and logs.
- Do not paste plan files or Terraform state into a report. Redact any value before you share output.
- Tests and fixtures must not contain real credentials, tokens or keys. Use obviously fake values.

If you find a real credential in the repository, report it through the private channel above and rotate the credential.
