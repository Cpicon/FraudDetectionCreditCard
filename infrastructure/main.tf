terraform {
  required_version = ">= 1.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "fraud-detection-tfstate"
    key            = "fraud-detection/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "fraud-detection-tfstate-locks"
  }
}

locals {
  # Map workspace to environment
  env_map = {
    default = "dev"
    dev     = "dev"
    stage   = "stage"
    prod    = "prod"
  }

  # Current environment
  environment = local.env_map[terraform.workspace]

  # Environment settings
  env_settings = {
    dev = {
      vpc_cidr = "10.0.0.0/24"
      tags = {
        Project     = "fraud-detection"
        Environment = "dev"
      }
    }
    stage = {
      vpc_cidr = "10.0.1.0/24"
      tags = {
        Project     = "fraud-detection"
        Environment = "stage"
      }
    }
    prod = {
      vpc_cidr = "10.0.2.0/24"
      tags = {
        Project     = "fraud-detection"
        Environment = "prod"
      }
    }
  }

  # Current environment settings
  current_env_settings = local.env_settings[local.environment]
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = local.current_env_settings.tags
  }
}

# Import modules as needed
# module "vpc" {
#   source = "./modules/vpc"
#   vpc_cidr = local.current_env_settings.vpc_cidr
#   environment = local.environment
# }

# module "sqs" {
#   source = "./modules/sqs"
#   environment = local.environment
# }

# module "lambda" {
#   source = "./modules/lambda"
#   environment = local.environment
# }

# And so on...

# Outputs
output "environment" {
  value = local.environment
}

output "vpc_cidr" {
  value = local.current_env_settings.vpc_cidr
} 