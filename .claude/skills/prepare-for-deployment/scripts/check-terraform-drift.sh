#!/usr/bin/env bash
# Check for drift between LocalStack-provisioned resources and .deploy/ Terraform scripts.
# Usage: ./check-terraform-drift.sh [terraform_dir]
# Exit codes: 0 = no drift, 1 = drift detected, 2 = error
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo '.')"
DEPLOY_DIR="${REPO_ROOT}/.deploy"
TERRAFORM_DIR="${1:-${DEPLOY_DIR}/dev}"
LOCALSTACK_PORT="${LOCALSTACK_PORT:-4566}"
LOCALSTACK_ENDPOINT="http://localhost:${LOCALSTACK_PORT}"

# --- Preflight checks ---

if [[ ! -d "$DEPLOY_DIR" ]]; then
  echo "ERROR: .deploy/ directory not found at ${DEPLOY_DIR}"
  echo "DRIFT: .deploy/ directory needs to be created"
  exit 1
fi

if [[ ! -d "$TERRAFORM_DIR" ]]; then
  echo "ERROR: Terraform directory not found: $TERRAFORM_DIR"
  echo "DRIFT: Environment directory needs to be created"
  exit 1
fi

if ! curl -sf "${LOCALSTACK_ENDPOINT}/_localstack/health" &>/dev/null; then
  echo "ERROR: LocalStack is not running. Cannot check drift."
  exit 2
fi

# --- Check Terraform validity ---

echo "=== Terraform Drift Check ==="
echo "Directory: ${TERRAFORM_DIR}"
echo ""

cd "$TERRAFORM_DIR"

# Validate Terraform syntax
echo "Validating Terraform syntax..."
if ! terraform validate 2>&1; then
  echo ""
  echo "DRIFT DETECTED: Terraform validation failed"
  echo "Fix: Update .tf files to resolve syntax/reference errors"
  exit 1
fi

# Check formatting
echo ""
echo "Checking Terraform formatting..."
FMT_OUTPUT=$(terraform fmt -check -diff 2>&1 || true)
if [[ -n "$FMT_OUTPUT" ]]; then
  echo "DRIFT DETECTED: Terraform formatting issues"
  echo "$FMT_OUTPUT"
  echo ""
  echo "Fix: Run 'terraform fmt' in ${TERRAFORM_DIR}"
  DRIFT_FOUND=true
else
  echo "Formatting: OK"
fi

# --- Check for new resources in LocalStack not in Terraform ---

echo ""
echo "Checking LocalStack resources against Terraform state..."

# Get resources from Terraform state (if it exists)
if [[ -f "terraform.tfstate" ]] || [[ -d ".terraform" ]]; then
  PLAN_OUTPUT=$(terraform plan -detailed-exitcode -input=false 2>&1 || true)
  PLAN_EXIT=$?

  if [[ $PLAN_EXIT -eq 2 ]]; then
    echo ""
    echo "DRIFT DETECTED: Terraform plan shows changes needed"
    echo "$PLAN_OUTPUT" | grep -E "^[[:space:]]*(#|~|\+|-)" | head -50
    echo ""
    echo "Fix: Review and apply changes to align .deploy/ with current state"
    exit 1
  elif [[ $PLAN_EXIT -eq 0 ]]; then
    echo "Terraform state: in sync"
  else
    echo "WARNING: Terraform plan failed (may be expected if using LocalStack override)"
    echo "$PLAN_OUTPUT" | tail -5
  fi
else
  echo "No Terraform state found (first run or state not initialized)"
fi

# --- Check required tags ---

echo ""
echo "Checking required tags in .tf files..."
REQUIRED_TAGS=("team" "environment" "service" "managed-by")
MISSING_TAGS=()

for tag in "${REQUIRED_TAGS[@]}"; do
  if ! grep -rq "\"${tag}\"" "$TERRAFORM_DIR"/*.tf 2>/dev/null; then
    MISSING_TAGS+=("$tag")
  fi
done

if [[ ${#MISSING_TAGS[@]} -gt 0 ]]; then
  echo "DRIFT DETECTED: Missing required tags: ${MISSING_TAGS[*]}"
  echo "Fix: Add tags block with: team, environment, service, managed-by"
  DRIFT_FOUND=true
else
  echo "Required tags: present"
fi

# --- Check naming convention ---

echo ""
echo "Checking naming conventions (gridx-{service}-{environment})..."
# Look for resource names that don't follow convention
NON_COMPLIANT=$(grep -rn 'name\s*=' "$TERRAFORM_DIR"/*.tf 2>/dev/null \
  | grep -v 'gridx-' \
  | grep -v '#' \
  | grep -v '//' \
  | grep -v 'tag' \
  | head -10 || true)

if [[ -n "$NON_COMPLIANT" ]]; then
  echo "WARNING: Possible naming convention violations:"
  echo "$NON_COMPLIANT"
  echo ""
  echo "Expected pattern: gridx-{service}-{environment}"
fi

# --- Check all environments ---

echo ""
echo "Checking environment parity..."
ENVIRONMENTS=("dev" "staging" "production")
MISSING_ENVS=()

for env in "${ENVIRONMENTS[@]}"; do
  if [[ ! -d "${DEPLOY_DIR}/${env}" ]]; then
    MISSING_ENVS+=("$env")
  fi
done

if [[ ${#MISSING_ENVS[@]} -gt 0 ]]; then
  echo "DRIFT DETECTED: Missing environment directories: ${MISSING_ENVS[*]}"
  echo "Fix: Create missing environment configs based on dev/"
  DRIFT_FOUND=true
else
  echo "All environments present: ${ENVIRONMENTS[*]}"
fi

# --- Summary ---

echo ""
echo "=== Summary ==="
if [[ "${DRIFT_FOUND:-false}" == "true" ]]; then
  echo "STATUS: DRIFT DETECTED — Terraform scripts need updates before deployment"
  exit 1
else
  echo "STATUS: NO DRIFT — Terraform scripts are up-to-date"
  exit 0
fi
