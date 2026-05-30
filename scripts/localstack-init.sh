#!/usr/bin/env sh
set -eu

LOCALSTACK_HOST="${LOCALSTACK_HOST:-localstack}"
LOCALSTACK_PORT="${LOCALSTACK_PORT:-4566}"
ENDPOINT="http://${LOCALSTACK_HOST}:${LOCALSTACK_PORT}"

BUCKET="${PACKVAULT_S3_BUCKET:-packvault}"
SECRET_ID="${PACKVAULT_SECRETS_MANAGER_SECRET_ID:-packvault/dev/encryption-key}"
SECRET_VALUE="${PACKVAULT_SECRETS_ENCRYPTION_KEY:-dev-local-encryption-key}"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "Initializing LocalStack resources at ${ENDPOINT}"

awslocal --endpoint-url="${ENDPOINT}" s3 mb "s3://${BUCKET}" 2>/dev/null || true

if ! awslocal --endpoint-url="${ENDPOINT}" secretsmanager describe-secret \
  --secret-id "${SECRET_ID}" >/dev/null 2>&1
then
  awslocal --endpoint-url="${ENDPOINT}" secretsmanager create-secret \
    --name "${SECRET_ID}" \
    --secret-string "${SECRET_VALUE}"
else
  awslocal --endpoint-url="${ENDPOINT}" secretsmanager put-secret-value \
    --secret-id "${SECRET_ID}" \
    --secret-string "${SECRET_VALUE}"
fi

echo "LocalStack init complete (bucket=${BUCKET}, secret=${SECRET_ID})"
