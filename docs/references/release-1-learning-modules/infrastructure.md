# Infrastructure: terraform, SES templates, scheduled reminder task

Release 1, ticket 14 (final ticket of the release). Declares the AWS footprint
Release 1's own features need, under `.deploy/dev`.

## What this ticket stands up

- A private S3 bucket for module assets (ticket 3): public access fully
  blocked, SSE-S3 encryption, versioning on, a lifecycle rule aborting
  incomplete multipart uploads, and a second lifecycle rule expiring
  noncurrent versions — versioning without it would grow the bucket's storage
  cost unbounded.
- A least-privilege IAM policy, scoped to `modules/*` object operations
  (`GetObject`/`PutObject`/`DeleteObject`), attached to the backend API's
  existing ECS task role.
- An ECS Fargate task definition for the reminder job (ticket 8), invoking the
  identical entrypoint — `python -m app.jobs.send_reminders` — the local
  `reminder-runner` compose service loops, with its own task role (separate
  from the backend API's — it only reads the database and sends mail, never
  touches module assets).
- An EventBridge Scheduler schedule invoking that task hourly by default,
  matching the local loop's cadence. The job itself is idempotent, so a
  schedule tighter than its own daily cadence logic is harmless, not a bug.
- Four SES templates (assignment × EN/DE, reminder × EN/DE) as the
  infrastructure inventory this ticket's checklist asks for.
- `terraform validate` runs clean. `terraform plan` was exercised against
  placeholder variable values with dummy AWS credentials in this environment
  (network reachable, request correctly rejected at `sts:GetCallerIdentity`
  with `InvalidClientTokenId`) — proving the configuration graph builds and
  the provider is reached, but a real `plan`/`apply` needs this project's
  actual AWS account and Release 0's resource names as input.

## What this ticket deliberately does **not** stand up

- **No VPC, ECS cluster, ALB, RDS, or application compute/network.** Those
  are Release 0's baseline stack (`docs/release-0-foundation/PRD.md`
  describes them: ECS Fargate behind an ALB, S3+CloudFront for the frontend),
  which does not exist in this repository yet. Release 1's stack takes the
  cluster ARN, subnet ids, security group ids, and the two existing task
  role/execution-role *names* as Terraform variables rather than creating or
  looking them up via `terraform_remote_state` — so this stack can be
  reviewed and `validate`d on its own before Release 0's ever lands, and the
  two releases' state files stay independent.
- **No Secrets Manager secrets.** `database_url_secret_arn` and
  `two_factor_encryption_key_secret_arn` are variables pointing at secrets
  Release 0's stack is expected to create; this stack only grants the
  execution role permission to read the two it needs for the reminder task.
- **No SES domain/identity verification.** `var.ses_sender_email` must
  already be a verified SES identity by the time this stack is applied —
  that verification (and the domain it lives under) is Release 0's
  responsibility, not repeated here.
- **The Terraform state backend bucket/lock table themselves.** `backend.tf`
  declares an `s3` backend with no inline bucket/key, supplied via
  `-backend-config` at `init` time, per
  `terraform-aws-provider-best-practices/backend.html` — account-level state
  infrastructure is bootstrapped once, outside any release's own stack.

## Two decisions worth knowing

### The SES templates are declared, not yet wired up

`app.security.mailer` (tickets 7 and 8) renders subject and body in Python —
the reminder headline varies by cadence checkpoint (`advance_7`, `due`,
`overdue_weekly`, …), which a static SES template can't express without a
conditional-logic rewrite of the mailer — and calls boto3's plain
`send_email`, not `SendTemplatedEmail`. The four `aws_ses_template` resources
here satisfy this ticket's own checklist item as infrastructure inventory,
but nothing in the application calls them yet. Wiring the mailer to them is
follow-up work, out of scope for an infrastructure-only ticket.

### "CloudFront distribution **or** dedicated origin" — dedicated origin, not CloudFront

Ticket 3 already separated the asset-delivery origin from the application
origin locally, by pointing `ASSET_ORIGIN` at LocalStack's own S3 endpoint —
the backend mints a boto3 **presigned S3 URL** (`generate_presigned_url`) and
307-redirects to it. A CloudFront distribution fronting the bucket would need
either a public bucket (ruled out) or **CloudFront signed URLs/cookies**,
which is a different signing mechanism from the one the backend already
implements and would mean reworking `app/storage.py`'s delivery path — a
larger change than this ticket's scope. A CloudFront Origin Access Control
restricting the bucket to CloudFront alone would additionally break the
existing presigned-URL flow outright, since a browser would be fetching the
object directly rather than through CloudFront.

So the "dedicated origin" here is the bucket's own regional S3 endpoint
(`aws_s3_bucket.assets.bucket_regional_domain_name`, exposed as the
`asset_origin` output) — origin-separated from the application exactly as
locally, with no change to how the backend signs or serves a URL. Revisiting
this for CloudFront (caching, a custom domain, WAF in front of asset
delivery) is a reasonable future ticket, not this one.
