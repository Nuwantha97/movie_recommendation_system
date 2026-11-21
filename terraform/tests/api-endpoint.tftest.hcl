mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = jsonencode({ Version = "2012-10-17", Statement = [] }) }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-southeast-2a", "ap-southeast-2b"] }
  }
}

run "assigned_hostname" {
  command = plan
  variables {
    use_cloudfront_api = true
  }
  assert {
    condition     = length(aws_cloudfront_distribution.api) == 1 && length(aws_vpc_security_group_ingress_rule.web) == 1 && aws_vpc_security_group_ingress_rule.web["80"].cidr_ipv4 == null
    error_message = "The automatic API needs a distribution and a restricted HTTP origin."
  }
}

run "custom_hostname" {
  command = plan
  variables {
    use_cloudfront_api = false
  }
  assert {
    condition     = length(aws_cloudfront_distribution.api) == 0 && aws_vpc_security_group_ingress_rule.web["443"].cidr_ipv4 == "0.0.0.0/0"
    error_message = "The custom API needs direct HTTPS access to Caddy."
  }
}
