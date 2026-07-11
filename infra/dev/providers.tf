# =============================================================================
# NISCHINT - Dev Environment Provider Configuration
# =============================================================================

provider "aws" {
  region = "ap-south-1"

  default_tags {
    tags = {
      Project     = "nischint"
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}
