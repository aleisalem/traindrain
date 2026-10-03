# --- Backend API task role: exactly the assets bucket operations the API
# performs (`app/storage.py`'s `put_asset`, `get_asset_bytes`, `copy_asset`,
# `delete_asset`, `presigned_asset_url`) and nothing else. Attached to the
# existing backend task role (Release 0) rather than creating a new one.

data "aws_iam_policy_document" "backend_assets_access" {
  statement {
    sid    = "ModuleAssetsObjectAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    # Namespaced under modules/ per `object_key()` — the policy can't be any
    # wider than the key scheme the application itself uses.
    resources = ["${aws_s3_bucket.assets.arn}/modules/*"]
  }
}

resource "aws_iam_policy" "backend_assets_access" {
  name        = "${local.name_prefix}-backend-assets-access"
  description = "Module-assets S3 access for the backend API task role."
  policy      = data.aws_iam_policy_document.backend_assets_access.json
}

resource "aws_iam_role_policy_attachment" "backend_assets_access" {
  role       = var.backend_task_role_name
  policy_arn = aws_iam_policy.backend_assets_access.arn
}

# --- Reminder task role: its own, separate from the backend API's. It never
# touches module assets — only reads the DB and sends mail — so it gets
# neither the S3 policy above nor any permission the API task role holds.

data "aws_iam_policy_document" "reminder_task_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "reminder_task" {
  name               = "${local.name_prefix}-reminder-task"
  assume_role_policy = data.aws_iam_policy_document.reminder_task_assume.json
}

data "aws_iam_policy_document" "reminder_task_permissions" {
  statement {
    sid       = "SendReminderMail"
    effect    = "Allow"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.ses_sender_email]
    }
  }
}

resource "aws_iam_role_policy" "reminder_task_permissions" {
  name   = "${local.name_prefix}-reminder-task-permissions"
  role   = aws_iam_role.reminder_task.id
  policy = data.aws_iam_policy_document.reminder_task_permissions.json
}

# --- Execution role: narrowly extended (Release 0 owns the role itself) so
# ECS can resolve the two `secrets` entries in the reminder task definition
# at launch. This is the one piece of this stack that reaches into a Release
# 0-owned resource, and it's additive — a policy attachment, not a change to
# the role's trust policy or its other permissions.

data "aws_iam_policy_document" "reminder_secrets_access" {
  statement {
    sid     = "ReadReminderTaskSecrets"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      var.database_url_secret_arn,
      var.two_factor_encryption_key_secret_arn,
    ]
  }
}

resource "aws_iam_policy" "reminder_secrets_access" {
  name        = "${local.name_prefix}-reminder-secrets-access"
  description = "Lets the shared ECS task execution role resolve the reminder task's injected secrets."
  policy      = data.aws_iam_policy_document.reminder_secrets_access.json
}

resource "aws_iam_role_policy_attachment" "reminder_secrets_access" {
  role       = var.ecs_task_execution_role_name
  policy_arn = aws_iam_policy.reminder_secrets_access.arn
}

# --- EventBridge Scheduler's own role: permission to launch exactly this
# task definition on exactly this cluster, and to pass exactly the two roles
# the task needs — nothing broader.

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler_invocation" {
  name               = "${local.name_prefix}-reminder-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_invocation_permissions" {
  statement {
    sid       = "RunReminderTask"
    effect    = "Allow"
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.reminder.arn]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [var.ecs_cluster_arn]
    }
  }

  statement {
    sid     = "PassReminderTaskRoles"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.reminder_task.arn,
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.ecs_task_execution_role_name}",
    ]
    condition {
      test     = "StringLike"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler_invocation_permissions" {
  name   = "${local.name_prefix}-reminder-scheduler-permissions"
  role   = aws_iam_role.scheduler_invocation.id
  policy = data.aws_iam_policy_document.scheduler_invocation_permissions.json
}
