
terraform {
  required_version = ">= 1.17.0"

  backend "s3" {
    key          = "movie-recommendation/production.tfstate"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}


provider "aws" {
  region = var.aws_region
}

