# The private object store module assets live in — mirrors `app/storage.py`'s
# own description of the bucket: public access blocked, encrypted at rest,
# objects reached only through a short-lived presigned URL the API mints
# after authorizing the caller against the module (`may_read_module` /
# `authorize_asset_access`). Nothing here makes an object public.

resource "aws_s3_bucket" "assets" {
  bucket = local.assets_bucket_name
}

resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "assets" {
  bucket = aws_s3_bucket.assets.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    apply_server_side_encryption_by_default {
      # AES256 (SSE-S3), matching `app/storage.py`'s own
      # `ServerSideEncryption: AES256` on every `put_object` call — the
      # bucket default is belt-and-braces alongside that, not a substitute.
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"
    filter {} # applies bucket-wide; required explicitly since provider v5

    abort_incomplete_multipart_upload {
      days_after_initiation = var.assets_bucket_multipart_abort_days
    }
  }

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {} # applies bucket-wide; required explicitly since provider v5

    noncurrent_version_expiration {
      noncurrent_days = var.assets_bucket_noncurrent_version_expiration_days
    }
  }
}

# Defense in depth alongside the public access block above: refuse any
# request that doesn't arrive over TLS, so a misconfigured client can never
# fall back to plaintext.
resource "aws_s3_bucket_policy" "assets_deny_insecure_transport" {
  bucket = aws_s3_bucket.assets.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.assets.arn,
          "${aws_s3_bucket.assets.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}
