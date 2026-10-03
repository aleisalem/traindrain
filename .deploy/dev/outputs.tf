output "assets_bucket_name" {
  description = "Set as ASSETS_BUCKET on the backend API."
  value       = aws_s3_bucket.assets.id
}

output "assets_bucket_arn" {
  value = aws_s3_bucket.assets.arn
}

output "asset_origin" {
  description = <<-EOT
    The assets bucket's own regional endpoint — the "dedicated origin,
    separate from the application origin" this ticket calls for (see
    docs/references/infrastructure.md for why this is the bucket's own
    endpoint rather than a CloudFront distribution). Set as the frontend
    build's ASSET_ORIGIN so the CSP's img-src names it, exactly as
    docker-compose's frontend service does locally with LocalStack's origin.
  EOT
  value       = "https://${aws_s3_bucket.assets.bucket_regional_domain_name}"
}

output "reminder_task_definition_arn" {
  value = aws_ecs_task_definition.reminder.arn
}

output "reminder_task_role_arn" {
  value = aws_iam_role.reminder_task.arn
}

output "reminder_schedule_arn" {
  value = aws_scheduler_schedule.reminder.arn
}

output "reminder_log_group_name" {
  value = aws_cloudwatch_log_group.reminder.name
}

output "ses_template_names" {
  value = {
    assignment_en = aws_ses_template.assignment_en.name
    assignment_de = aws_ses_template.assignment_de.name
    reminder_en   = aws_ses_template.reminder_en.name
    reminder_de   = aws_ses_template.reminder_de.name
  }
}
