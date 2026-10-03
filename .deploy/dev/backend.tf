# Remote state, per the project's Terraform backend best practices
# (docs.aws.amazon.com/prescriptive-guidance/.../terraform-aws-provider-best-practices/backend.html):
# state lives in S3, locked via the table's native S3 locking (Terraform >= 1.9,
# no separate DynamoDB table needed), never on a laptop disk.
#
# The bucket/table themselves are account bootstrapping, not part of this
# release's stack, so their names are supplied per-account via
# `-backend-config` rather than hardcoded here:
#
#   terraform init \
#     -backend-config="bucket=<your-tfstate-bucket>" \
#     -backend-config="key=traindrain/dev/release-1.tfstate" \
#     -backend-config="region=eu-central-1" \
#     -backend-config="use_lockfile=true"
terraform {
  backend "s3" {}
}
