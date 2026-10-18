# terraform-data fixture

This fixture is for CI only. It is not a module and must not be used as one.

The `terraform-fixture` workflow copies it to a scratch directory, applies it there to create local state, and changes the default of `v` in that copy so that the replacement check has a real replacement to find. The repository copy is never changed by the workflow.
