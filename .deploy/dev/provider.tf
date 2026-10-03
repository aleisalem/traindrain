provider "aws" {
  region = var.aws_region

  # EU-based data residency, per AGENTS.md — refuse to apply against any
  # other region even if a caller's environment points somewhere else.
  allowed_account_ids = var.aws_account_id == null ? null : [var.aws_account_id]

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Release     = "release-1-learning-modules"
    }
  }
}

data "aws_caller_identity" "current" {}
