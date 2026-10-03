# SES templates for the assignment and reminder emails, in both languages, as
# this ticket's own inventory of required infrastructure.
#
# IMPORTANT — these are declared but not yet wired up: `app.security.mailer`
# (tickets 7 and 8) sends with a plain `ses_client.send_email(...)`, rendering
# subject and body in Python before the call, not `SendTemplatedEmail`.
# Switching the mailer over to these templates is follow-up work, not part of
# this infrastructure ticket; see `docs/references/infrastructure.md`.
#
# The sender identity itself (`var.ses_sender_email`) is verified as part of
# Release 0's baseline stack, not here — a template can be created unverified,
# but sending with it still requires a verified identity at send time.

resource "aws_ses_template" "assignment_en" {
  name    = "${local.name_prefix}-assignment-en"
  subject = "New training assigned to you on TrainDrain"
  text    = "You have been assigned the following training: {{module_title}}\n\n{{due_line}}Open it here:\n{{module_url}}"
  html    = "<p>You have been assigned the following training: <strong>{{module_title}}</strong></p><p>{{due_line}}</p><p><a href=\"{{module_url}}\">Open it here</a></p>"
}

resource "aws_ses_template" "assignment_de" {
  name    = "${local.name_prefix}-assignment-de"
  subject = "Ihnen wurde ein neues Training auf TrainDrain zugewiesen"
  text    = "Ihnen wurde folgendes Training zugewiesen: {{module_title}}\n\n{{due_line}}Öffnen Sie es hier:\n{{module_url}}"
  html    = "<p>Ihnen wurde folgendes Training zugewiesen: <strong>{{module_title}}</strong></p><p>{{due_line}}</p><p><a href=\"{{module_url}}\">Öffnen Sie es hier</a></p>"
}

resource "aws_ses_template" "reminder_en" {
  name    = "${local.name_prefix}-reminder-en"
  subject = "Reminder: training due on TrainDrain"
  text    = "{{headline}}\n\nOpen it here:\n{{module_url}}"
  html    = "<p>{{headline}}</p><p><a href=\"{{module_url}}\">Open it here</a></p>"
}

resource "aws_ses_template" "reminder_de" {
  name    = "${local.name_prefix}-reminder-de"
  subject = "Erinnerung: Fälliges Training auf TrainDrain"
  text    = "{{headline}}\n\nÖffnen Sie es hier:\n{{module_url}}"
  html    = "<p>{{headline}}</p><p><a href=\"{{module_url}}\">Öffnen Sie es hier</a></p>"
}
