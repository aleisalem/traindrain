# TrainDrain — `dev` — Release 1 infrastructure

Terraform for Release 1's own AWS footprint: the module-assets S3 bucket, the
scheduled reminder ECS task, and SES templates. See
`docs/references/infrastructure.md` for what this stack does and does not
stand up — in particular, it assumes Release 0's VPC/ECS cluster/ALB already
exist and takes them as input variables rather than creating them.

## Prerequisites

- An AWS account, and an S3 bucket (plus Terraform ≥ 1.9's native S3 locking)
  to hold this stack's remote state — bootstrapped once, outside this stack.
- Release 0's stack already applied, so you have: an ECS cluster ARN, private
  subnet ids, a security group for ECS tasks, the backend API's task role
  name, a shared task execution role name, and Secrets Manager ARNs for
  `DATABASE_URL` and `TWO_FACTOR_ENCRYPTION_KEY`.
- A backend image already pushed to ECR.

## Running it

```bash
cd .deploy/dev

terraform init \
  -backend-config="bucket=<your-tfstate-bucket>" \
  -backend-config="key=traindrain/dev/release-1.tfstate" \
  -backend-config="region=eu-central-1" \
  -backend-config="use_lockfile=true"

# Fill in every variable without a default in variables.tf — the Release 0
# values above, plus your backend image URI. A dev.auto.tfvars here is
# gitignored, so that's the natural place to keep them.
terraform plan
terraform apply
```

After `apply`, set the backend API's `ASSETS_BUCKET` to the
`assets_bucket_name` output, and the frontend build's `ASSET_ORIGIN` to the
`asset_origin` output.

## Validating without an AWS account

```bash
terraform init -backend=false   # skips remote state, still resolves providers
terraform validate
```

`terraform plan`/`apply` need a real account — they call `sts:GetCallerIdentity`
during provider setup, and `plan` reads the AWS API for Release 0's named
resources even on a from-scratch stack.
