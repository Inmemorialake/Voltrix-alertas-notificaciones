variable "region" {
  description = "Región de AWS."
  type        = string
  default     = "us-east-2"
}

variable "instance_type" {
  description = "Tipo de instancia. Debe ser elegible para la capa gratuita de la cuenta (se verifica en el plan)."
  type        = string
  default     = "t3.micro"
}

variable "ssh_cidr" {
  description = "Rango que puede entrar por SSH (22). Recomendado: su IP pública con /32."
  type        = string
  default     = "0.0.0.0/0"
}

variable "api_cidr" {
  description = "Rango que puede consumir la API (8080). Abierto para que los otros equipos la consuman."
  type        = string
  default     = "0.0.0.0/0"
}

variable "repo_url" {
  description = "Repositorio público que se clona en la instancia."
  type        = string
  default     = "https://github.com/Inmemorialake/Voltrix-alertas-notificaciones.git"
}

variable "repo_ref" {
  description = "Rama o etiqueta a desplegar."
  type        = string
  default     = "main"
}

variable "telemetria_url" {
  description = "URL base de Telemetría de Plantas (Equipo 2). Vacía: lecturas de ejemplo."
  type        = string
  default     = ""
}

variable "nombre" {
  description = "Prefijo de los recursos."
  type        = string
  default     = "voltrix-alertas"
}
