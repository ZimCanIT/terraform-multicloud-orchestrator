---
type: llm
---

PASS if the reply asks which cloud or clouds to target (AWS, Azure, GCP or OCI) and which provider-pinning strategy to use (exact, pessimistic-minor, pessimistic-patch or latest-stable-and-pin), and does not produce Terraform resource blocks yet.
FAIL if the reply writes Terraform resources without asking, asks only one of the two questions, or asks neither.
