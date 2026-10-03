# The scheduled reminder job: an ECS Fargate task invoking the exact same
# entrypoint (`python -m app.jobs.send_reminders`) the local `reminder-runner`
# compose service loops, per `docs/references/reminders.md`. EventBridge
# Scheduler triggers it on `var.reminder_schedule_expression`; the job itself
# is idempotent, so a shorter interval than its own daily cadence is harmless.

resource "aws_cloudwatch_log_group" "reminder" {
  name              = "/ecs/${local.name_prefix}-reminder"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_task_definition" "reminder" {
  family                   = "${local.name_prefix}-reminder"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.reminder_task_cpu
  memory                   = var.reminder_task_memory
  execution_role_arn       = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.ecs_task_execution_role_name}"
  task_role_arn            = aws_iam_role.reminder_task.arn

  container_definitions = jsonencode([
    {
      name    = "reminder"
      image   = var.backend_image
      command = ["python", "-m", "app.jobs.send_reminders"]
      # `docker-entrypoint.sh` runs `alembic upgrade head` before this,
      # identically to every other invocation of the backend image — the
      # same migration-on-start already in use locally, not something new
      # introduced for this task.
      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "SES_SENDER_EMAIL", value = var.ses_sender_email },
      ]
      secrets = [
        { name = "DATABASE_URL", valueFrom = var.database_url_secret_arn },
        { name = "TWO_FACTOR_ENCRYPTION_KEY", valueFrom = var.two_factor_encryption_key_secret_arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.reminder.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "reminder"
        }
      }
    }
  ])
}

resource "aws_scheduler_schedule" "reminder" {
  name       = "${local.name_prefix}-reminder"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.reminder_schedule_expression

  target {
    arn      = var.ecs_cluster_arn
    role_arn = aws_iam_role.scheduler_invocation.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.reminder.arn
      launch_type         = "FARGATE"
      task_count          = 1

      network_configuration {
        subnets          = var.private_subnet_ids
        security_groups  = var.ecs_task_security_group_ids
        assign_public_ip = false
      }
    }

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}
