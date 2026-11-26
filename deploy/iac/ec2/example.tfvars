# Copie a terraform.tfvars (ignorado por git) y ajuste. Terraform lo lee automáticamente.
instance_type = "t3.micro"
# Rango de salida de la red de la universidad (la IP cambia dentro de este /22).
ssh_cidr = "45.5.164.0/22"
