locals {
  runtime_secret_name = "${var.project_name}/production"
}

resource "aws_s3_bucket" "releases" {
  bucket_prefix = "movie-recs-release-"
}

resource "aws_s3_bucket_public_access_block" "releases" {
  bucket                  = aws_s3_bucket.releases.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "releases" {
  bucket = aws_s3_bucket.releases.id
  rule {
    id     = "expire-source-archives"
    status = "Enabled"
    filter {
      prefix = "releases/"
    }
    expiration {
      days = 7
    }
  }
}

resource "aws_iam_role_policy" "ec2_deployment" {
  role = aws_iam_role.ec2.id
  name = "read-release-and-runtime-secrets"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.releases.arn}/releases/*"
      },
      {
        Effect = "Allow"
        Action = "secretsmanager:GetSecretValue"
        Resource = [
          aws_db_instance.postgres.master_user_secret[0].secret_arn,
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${local.runtime_secret_name}-??????"
        ]
      }
    ]
  })
}
