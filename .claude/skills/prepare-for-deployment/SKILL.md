---
name: prepare-for-deployment
description: Spin up LocalStack, deploy the application against simulated AWS services, and verify it works before real deployment. Use when a feature is complete and tests pass, user says "prepare for deployment", "pre-deploy", "simulate deployment", or wants to verify the app works against AWS services locally before pushing to a real environment.
---

# Prepare for Deployment

Validate that a completed feature works against simulated AWS services via LocalStack before deploying to a real environment.

## Quick Start

1. Detect which AWS services the feature requires (from Terraform scripts in `.deploy/`)
2. Start LocalStack with those services
3. Deploy the application locally against LocalStack
4. Run integration tests against the simulated environment
5. **Enforce `.deploy/` Terraform scripts are up-to-date** (mandatory gate)
6. Report results and readiness

## Workflow

### Step 1 — Identify Required Services

- [ ] Parse `.deploy/` Terraform files for AWS resource declarations
- [ ] Cross-reference with `docker-compose.yml` for existing service definitions
- [ ] Build a service manifest (S3, DynamoDB, Lambda, SQS, SNS, RDS, etc.)

### Step 2 — Validate Prerequisites

- [ ] Confirm LocalStack CLI is installed (`localstack --version`)
- [ ] Confirm Docker is running
- [ ] Check for LocalStack auth token in `.env` or environment
- [ ] Verify all tests pass before proceeding (`go test ./...` for backend)

### Step 3 — Start LocalStack Environment

- [ ] Run `scripts/start-localstack.sh` with detected services
- [ ] Wait for LocalStack readiness (health check)
- [ ] Provision AWS resources using Terraform against LocalStack endpoint

### Step 4 — Deploy Application Locally

- [ ] Build backend (`go build ./...`)
- [ ] Build frontend (if applicable)
- [ ] Start application containers via `docker-compose` with LocalStack endpoints
- [ ] Wait for application health checks

### Step 5 — Verify Deployment

- [ ] Run integration tests against local deployment
- [ ] Verify API endpoints respond correctly
- [ ] Check that AWS service interactions work (e.g., S3 uploads, DynamoDB reads)
- [ ] Validate no error logs in application output

### Step 6 — Enforce Terraform Script Updates (MANDATORY)

After successful LocalStack verification, the `.deploy/` Terraform scripts MUST be updated to reflect the validated state. This step is **non-optional** — a deployment is not considered ready until Terraform scripts match what was tested.

- [ ] Compare the Terraform resources that were provisioned against what exists in `.deploy/dev/`, `.deploy/staging/`, and `.deploy/production/`
- [ ] Identify any drift: new resources added during development, changed configurations, removed resources
- [ ] Update `.deploy/dev/` to exactly match the validated LocalStack configuration
- [ ] Propagate relevant changes to `.deploy/staging/` and `.deploy/production/` (with environment-specific values)
- [ ] Ensure resource naming follows gridX conventions: `gridx-{service}-{environment}`
- [ ] Ensure all resources have required tags: `team`, `environment`, `service`, `managed-by`
- [ ] Run `terraform validate` on all updated environments
- [ ] Run `terraform fmt` to ensure consistent formatting
- [ ] Commit the Terraform updates with a descriptive message referencing the feature

**If Terraform scripts are already up-to-date**: Confirm this explicitly in the report — do not skip the verification.

**If updates are needed but conflict with existing resources**: Flag to the user with a diff and ask for resolution before proceeding.

### Step 7 — Report & Cleanup

- [ ] Summarize results: services tested, endpoints verified, Terraform scripts updated
- [ ] List all files modified in `.deploy/` with a brief description of changes
- [ ] If all checks pass: confirm ready for deployment
- [ ] If issues found: list failures with remediation steps
- [ ] Offer to tear down LocalStack environment

## Conditional Logic

| Condition | Action |
|-----------|--------|
| No `.deploy/` directory | Warn user; ask which services to simulate |
| LocalStack not installed | Run installation steps (see REFERENCE.md) |
| Auth token missing | Prompt user to provide or retrieve from `.env` |
| Tests fail before simulation | Block deployment preparation; report failures |
| Feature uses unsupported service | Warn and skip that service; note in report |
| Terraform scripts outdated | **Block** deployment readiness; update scripts first |
| Terraform update conflicts with existing | Show diff to user; require manual resolution |
| `.deploy/` missing an environment dir | Create it from the validated dev configuration |

## Reference

See [REFERENCE.md](REFERENCE.md) for:
- LocalStack installation and configuration
- Supported AWS services
- Terraform LocalStack provider setup
- gridX ops repo patterns
