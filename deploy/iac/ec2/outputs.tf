output "ip_publica" {
  description = "IP pública de la instancia (cambia si la instancia se detiene y arranca)."
  value       = aws_instance.api.public_ip
}

output "url_base" {
  description = "URL base para la hoja Coordinacion_Voltrix."
  value       = "http://${aws_instance.api.public_ip}:8080"
}

output "url_health" {
  value = "http://${aws_instance.api.public_ip}:8080/health"
}

output "url_openapi" {
  value = "http://${aws_instance.api.public_ip}:8080/openapi.yaml"
}

output "ssh" {
  description = "Comando para entrar a la instancia."
  value       = "ssh -i ${local_sensitive_file.clave_privada.filename} ubuntu@${aws_instance.api.public_ip}"
}

output "tipo_instancia" {
  value = "${var.instance_type} (${local.arquitectura}, ${data.aws_ec2_instance_type.elegido.memory_size} MiB)"
}
