# =============================================================================
# NISCHINT - Staging Environment Backend Configuration
# =============================================================================

terraform {
  backend "s3" {
    bucket         = "nischint-terraform-state"
    key            = "env/staging/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "nischint-terraform-lock"
    encrypt        = true
  }
}
