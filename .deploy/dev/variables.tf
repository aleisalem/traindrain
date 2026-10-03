# --- Project-wide ----------------------------------------------------------

variable "project_name" {
  description = "Short name used to prefix every resource and tag."
  type        = string
  default     = "traindrain"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region. EU-based per the project's data-residency posture (AGENTS.md)."
  type        = string
  default     = "eu-central-1"

  validation {
    condition     = can(regex("^eu-", var.aws_region))
    error_message = "This project requires an EU-based AWS region."
  }
}

variable "aws_account_id" {
  description = "If set, the provider refuses to apply against any other account."
  type        = string
  default     = null
}

# --- Release 0 baseline (assumed to already exist) --------------------------
#
# This stack adds Release 1's own resources to a network and compute
# footprint that Release 0's own `.deploy/dev` stack is responsible for
# standing up. None of it is created here — these are references to what
# Release 0 is expected to already provide, kept as plain variables (rather
# than a `terraform_remote_state` data source) so this stack can still be
# planned and reviewed on its own before Release 0's stack exists in this
# repository.

variable "ecs_cluster_arn" {
  description = "ARN of the ECS cluster (Release 0) the reminder task runs on."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet ids (Release 0's VPC) the reminder task runs in."
  type        = list(string)
}

variable "ecs_task_security_group_ids" {
  description = "Security group ids (Release 0) attached to the reminder task's ENI."
  type        = list(string)
}

variable "ecs_task_execution_role_name" {
  description = <<-EOT
    Name of the existing ECS task execution role (Release 0) used to pull the
    container image and ship logs to CloudWatch. This stack attaches one
    additional, narrowly-scoped policy to it so the reminder task's secrets
    can be injected at launch — it does not create or otherwise own this role.
  EOT
  type        = string
}

variable "backend_task_role_name" {
  description = <<-EOT
    Name of the existing backend API's ECS task role (Release 0). This stack
    attaches the module-assets S3 policy to it; it does not create or
    otherwise own the role.
  EOT
  type        = string
}

variable "backend_image" {
  description = "Container image URI (ECR) for the backend, reused for the reminder task."
  type        = string
}

variable "database_url_secret_arn" {
  description = "Secrets Manager secret ARN holding the backend's DATABASE_URL (Release 0)."
  type        = string
}

variable "two_factor_encryption_key_secret_arn" {
  description = <<-EOT
    Secrets Manager secret ARN holding TWO_FACTOR_ENCRYPTION_KEY (Release 0).
    The reminder job never reads a 2FA secret itself, but it imports the same
    `app.core.config.Settings` the API does, which requires this field — so
    it has to be supplied even here.
  EOT
  type        = string
}

# --- Module assets (ticket 3 / this ticket) ---------------------------------

variable "asset_url_ttl_seconds" {
  description = "Presigned asset URL TTL. Must match the backend's ASSET_URL_TTL_SECONDS."
  type        = number
  default     = 300
}

variable "assets_bucket_multipart_abort_days" {
  description = "Days after which an incomplete multipart upload is aborted and its parts freed."
  type        = number
  default     = 7
}

variable "assets_bucket_noncurrent_version_expiration_days" {
  description = <<-EOT
    Versioning is required by this ticket; left unbounded, every overwritten
    or deleted asset's prior version would accumulate storage cost forever.
    This expires noncurrent versions after N days rather than keeping them
    indefinitely.
  EOT
  type        = number
  default     = 90
}

# --- Mail (SES) --------------------------------------------------------------

variable "ses_sender_email" {
  description = "Verified SES sender identity. Verification itself is Release 0's responsibility."
  type        = string
  default     = "no-reply@traindrain.local"
}

# --- Reminder schedule --------------------------------------------------------

variable "reminder_schedule_expression" {
  description = <<-EOT
    EventBridge Scheduler expression for the reminder job. Hourly by default,
    matching the local `reminder-runner` loop; the job itself is idempotent,
    so a tighter interval than the daily cadence it computes is harmless.
  EOT
  type        = string
  default     = "rate(1 hour)"
}

variable "reminder_task_cpu" {
  description = "Fargate task-level vCPU units for the reminder task."
  type        = string
  default     = "256"
}

variable "reminder_task_memory" {
  description = "Fargate task-level memory (MiB) for the reminder task."
  type        = string
  default     = "512"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the reminder task's log group."
  type        = number
  default     = 30
}
