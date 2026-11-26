# Componente B: una instancia EC2 con Docker que levanta deploy/compose/docker-compose.yml.

data "aws_ec2_instance_type" "elegido" {
  instance_type = var.instance_type
}

locals {
  arquitectura = contains(data.aws_ec2_instance_type.elegido.supported_architectures, "arm64") ? "arm64" : "amd64"
}

# Ubuntu 24.04 LTS oficial de Canonical, publicada como parámetro SSM (sin IDs de AMI fijos).
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/${local.arquitectura}/hvm/ebs-gp3/ami-id"
}

data "aws_vpc" "default" {
  default = true
}

# ------------------------------ acceso SSH ------------------------------
resource "tls_private_key" "ssh" {
  algorithm = "ED25519"
}

resource "aws_key_pair" "ssh" {
  key_name   = "${var.nombre}-ssh"
  public_key = tls_private_key.ssh.public_key_openssh
}

resource "local_sensitive_file" "clave_privada" {
  filename        = "${path.module}/${var.nombre}.pem"
  content         = tls_private_key.ssh.private_key_openssh
  file_permission = "0600"
}

# ---------------------------- security group ----------------------------
resource "aws_security_group" "api" {
  name        = "${var.nombre}-sg"
  description = "Alertas y Notificaciones: solo SSH y API (8080)"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "ssh" {
  security_group_id = aws_security_group.api.id
  description       = "SSH"
  cidr_ipv4         = var.ssh_cidr
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
}

resource "aws_vpc_security_group_ingress_rule" "api" {
  security_group_id = aws_security_group.api.id
  description       = "API Alertas y Notificaciones"
  cidr_ipv4         = var.api_cidr
  ip_protocol       = "tcp"
  from_port         = 8080
  to_port           = 8080
}

# Salida abierta: apt, GitHub, Docker Hub y Telemetría del Equipo 2.
resource "aws_vpc_security_group_egress_rule" "todo" {
  security_group_id = aws_security_group.api.id
  description       = "Salida"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# -------------------------------- instancia --------------------------------
resource "aws_instance" "api" {
  ami                         = data.aws_ssm_parameter.ubuntu.insecure_value
  instance_type               = var.instance_type
  key_name                    = aws_key_pair.ssh.key_name
  vpc_security_group_ids      = [aws_security_group.api.id]
  associate_public_ip_address = true

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    repo_url       = var.repo_url
    repo_ref       = var.repo_ref
    telemetria_url = var.telemetria_url
  })
  user_data_replace_on_change = true

  metadata_options {
    http_tokens   = "required" # IMDSv2
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 8 # GiB; la capa gratuita cubre hasta 30 GiB de EBS
    encrypted   = true
  }

  # Evita sorpresas en la factura: falla en el plan si el tipo no es elegible en esta cuenta.
  lifecycle {
    precondition {
      condition     = data.aws_ec2_instance_type.elegido.free_tier_eligible
      error_message = "El tipo ${var.instance_type} no es elegible para la capa gratuita en esta cuenta y región."
    }
  }

  tags = {
    Name = var.nombre
  }
}
