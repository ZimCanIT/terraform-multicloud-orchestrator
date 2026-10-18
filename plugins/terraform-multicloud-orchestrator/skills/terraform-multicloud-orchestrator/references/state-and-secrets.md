# State and secrets

Terraform state can hold secrets in plain text, so treat state files and their backends as sensitive.

## Remote backends and locking
Remote state with locking is required for shared environments, so two runs cannot change the same state at once. Restrict who can read the state store, because anyone who can read state can read its secrets.

- Unverified (2026-10-18): confirm backend options for your Terraform version. AWS: the `s3` backend, with locking configured.
- Unverified (2026-10-18): confirm backend options for your Terraform version. Azure: the `azurerm` backend, which stores state in Azure Blob Storage.
- Unverified (2026-10-18): confirm backend options for your Terraform version. Google Cloud: the `gcs` backend, which stores state in a Cloud Storage bucket.
- Unverified (2026-10-18): confirm backend options for your Terraform version. OCI: the `oci` backend, which stores state in Object Storage.

## Secrets in state
- State can contain secrets, including values returned by data sources and values set in resource arguments.
- Marking a variable or output `sensitive` hides it from CLI output but does not keep it out of state.
- Unverified (2026-10-18): confirm the minimum Terraform version and provider support. Ephemeral values and write-only arguments keep secrets out of state where the Terraform version and provider support them.

## Module vetting
- Pin module git sources to a commit SHA with `?ref=<sha>`, for example `git::https://example.com/org/module.git?ref=<sha>`.
- Review a module's source and its dependencies before use.
- Pin registry modules to a version.
