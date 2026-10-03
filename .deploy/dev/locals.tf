locals {
  name_prefix = "${var.project_name}-${var.environment}"

  # Globally unique without manual coordination: S3 bucket names are
  # account-and-region-independent, so the account id disambiguates two
  # deployments that would otherwise both want "traindrain-assets-dev".
  assets_bucket_name = "${local.name_prefix}-assets-${data.aws_caller_identity.current.account_id}"
}
