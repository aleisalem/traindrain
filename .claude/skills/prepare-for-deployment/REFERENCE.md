# Reference: Prepare for Deployment

## LocalStack Installation

### macOS (Homebrew)

```bash
brew install localstack/tap/localstack-cli
```

### pip

```bash
pip install localstack
```

### Verify installation

```bash
localstack --version
```

## LocalStack Configuration

### Auth Token

LocalStack Pro requires an auth token. Retrieve from:
1. `.env` file: `LOCALSTACK_AUTH_TOKEN=...`
2. Environment variable: `export LOCALSTACK_AUTH_TOKEN=...`

### Terraform Provider for LocalStack

Add to your Terraform configuration:

```hcl
provider "aws" {
  access_key                  = "test"
  secret_key                  = "test"
  region                      = "eu-central-1"

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    s3       = "http://localhost:4566"
    dynamodb = "http://localhost:4566"
    lambda   = "http://localhost:4566"
    sqs      = "http://localhost:4566"
    sns      = "http://localhost:4566"
    iam      = "http://localhost:4566"
    sts      = "http://localhost:4566"
    # Add more as needed
  }
}
```

### Supported Services (Community Edition)

| Service | Endpoint |
|---------|----------|
| S3 | `http://localhost:4566` |
| DynamoDB | `http://localhost:4566` |
| SQS | `http://localhost:4566` |
| SNS | `http://localhost:4566` |
| Lambda | `http://localhost:4566` |
| IAM | `http://localhost:4566` |
| CloudFormation | `http://localhost:4566` |
| CloudWatch | `http://localhost:4566` |
| Secrets Manager | `http://localhost:4566` |

### Pro Services (require auth token)

| Service | Endpoint |
|---------|----------|
| RDS | `http://localhost:4566` |
| ECS | `http://localhost:4566` |
| EKS | `http://localhost:4566` |
| Cognito | `http://localhost:4566` |
| API Gateway v2 | `http://localhost:4566` |

## gridX Ops Repo Patterns

Reference: https://github.com/grid-x/ops

Key patterns to follow:
- All infrastructure in `eu-central-1`
- Terraform state stored in S3 with DynamoDB locking
- Naming convention: `gridx-{service}-{environment}`
- Tags: `team`, `environment`, `service`, `managed-by`

## Environment Variables for Local Deployment

When running against LocalStack, override AWS SDK configuration:

```bash
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=eu-central-1
```

## Health Check Endpoints

- LocalStack: `http://localhost:4566/_localstack/health`
- Application backend: `http://localhost:8080/health` (convention)
- Application frontend: `http://localhost:3000` (convention)

## Troubleshooting

| Issue | Solution |
|-------|----------|
| LocalStack won't start | Check Docker is running: `docker ps` |
| Service not available | Verify service is in `SERVICES` env var or config |
| Terraform apply fails | Check endpoint URLs match LocalStack port |
| Connection refused | Wait for health check; LocalStack may still be starting |
| Auth token invalid | Re-export `LOCALSTACK_AUTH_TOKEN` from `.env` |
