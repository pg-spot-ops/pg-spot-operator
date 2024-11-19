terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  user = "pg-spot-operator"
  region = "eu-north-1"
}

resource "aws_iam_user" "user" {
  name          = local.user
}

resource "aws_iam_user_policy" "user_policy" {
  name = "pg-spot-operator-region-limited"
  user = aws_iam_user.user.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "ec2:Describe*",
          "pricing:*",
          "cloudwatch:ListMetrics",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:Describe*",
          "ec2:RunInstances",
          "ec2:TerminateInstances",
          "ec2:StartInstances",
          "ec2:StopInstances",
          "ec2:CreateTags",
          "ec2:CreateNetworkInterface",
          "ec2:DeleteNetworkInterface",
          "ec2:AllocateAddress",
          "ec2:AssociateAddress",
          "ec2:DisassociateAddress",
          "ec2:ReleaseAddress",
          "ec2:*Volume*",
# S3 required for pgBackRest PITR archiving
#           "s3:ListBucket*",
#           "s3:ListMultipart*",
#           "s3:PutObject",
#           "s3:GetObject",
#           "s3:GetObjectVersion",
#           "s3:DeleteObject",
#           "s3:DeleteObjectVersion"
        ]
        Effect   = "Allow"
        Resource = "*"
         Condition = {
            "StringEquals" = {
              "aws:RequestedRegion": local.region
            }
          }
      },
    ]
  })
}

resource "aws_iam_access_key" "user_access_key" {
  user       = local.user
  depends_on = [aws_iam_user.user]
}

output "credentials" {
  value = {
    "key"      = aws_iam_access_key.user_access_key.id
    "secret"   = aws_iam_access_key.user_access_key.secret
  }
  sensitive = true
}

# terraform output -json
