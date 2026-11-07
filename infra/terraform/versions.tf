terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "nexus-architecture"
      ManagedBy   = "terraform"
      Environment = var.environment
      # Facilita achar e destruir tudo que este projeto criou.
      CostCenter = "nexus-experimental"
    }
  }
}
