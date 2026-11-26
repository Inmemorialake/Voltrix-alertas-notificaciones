variable "floci_endpoint" {
  description = "Endpoint de Floci."
  type        = string
  default     = "http://localhost:4566"
}

variable "floci_access_key" {
  description = "Credencial de Floci. 12 dígitos: Floci la usa también como account ID."
  type        = string
  default     = "000000000000"
}

variable "floci_secret_key" {
  type    = string
  default = "test"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "cluster_name" {
  type    = string
  default = "voltrix-alertas"
}

variable "kubernetes_version" {
  description = "Versión de Kubernetes (Floci soporta 1.28 a 1.36)."
  type        = string
  default     = "1.33"
}
