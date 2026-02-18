terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.50"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
  }

  # Remote state backend — config is supplied at init time via:
  #   terraform init -backend-config=backend.s3.tfbackend
  # Copy backend.s3.tfbackend.example → backend.s3.tfbackend and fill in your values.
  # To use local state only (not recommended for shared/prod), run:
  #   terraform init -backend=false
  backend "s3" {}
}
