terraform {
  required_version = ">= 1.5.0"
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

resource "local_file" "demo_marker" {
  filename = "${path.module}/demo-marker.txt"
  content  = "rightsized runner executed terraform at ${timestamp()}\n"
}
