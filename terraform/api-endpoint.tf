variable "use_cloudfront_api" {
  description = "Serve the API on an AWS-assigned HTTPS hostname"
  type        = bool
  default     = false
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  count = var.use_cloudfront_api ? 1 : 0
  name  = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_cloudfront_distribution" "api" {
  count           = var.use_cloudfront_api ? 1 : 0
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.project_name} API"

  origin {
    domain_name = aws_eip.backend.public_dns
    origin_id   = "backend"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60
    }
  }

  default_cache_behavior {
    target_origin_id       = "backend"
    viewer_protocol_policy = "https-only"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    # AWS managed CachingDisabled and AllViewer (includes Host, Origin and query strings).
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

output "cloudfront_api_base" {
  value = var.use_cloudfront_api ? "https://${aws_cloudfront_distribution.api[0].domain_name}/api" : null
}
