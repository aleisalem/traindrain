#!/usr/bin/env bash
# Tear down LocalStack and clean up generated files.
# Usage: ./teardown-localstack.sh [terraform_dir]
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo '.')"
TERRAFORM_DIR="${1:-${REPO_ROOT}/.deploy/dev}"

echo "Tearing down LocalStack environment..."

# --- Destroy Terraform resources (if applicable) ---

OVERRIDE_FILE="${TERRAFORM_DIR}/localstack_override.tf"
if [[ -f "$OVERRIDE_FILE" ]]; then
  echo "Destroying Terraform-managed resources..."
  cd "$TERRAFORM_DIR"
  terraform destroy -auto-approve -input=false 2>/dev/null || true
  rm -f "$OVERRIDE_FILE"
  rm -f localstack.tfplan
  rm -rf .terraform
  rm -f .terraform.lock.hcl
  echo "Removed Terraform override and state files."
  cd "$REPO_ROOT"
fi

# --- Stop LocalStack ---

if command -v localstack &>/dev/null; then
  echo "Stopping LocalStack..."
  localstack stop 2>/dev/null || true
  echo "LocalStack stopped."
else
  echo "LocalStack CLI not found; attempting Docker stop..."
  docker stop localstack-main 2>/dev/null || true
  docker rm localstack-main 2>/dev/null || true
fi

echo ""
echo "Teardown complete."
