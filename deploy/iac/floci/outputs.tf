output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.this.endpoint
}

output "cluster_role_arn" {
  value = aws_iam_role.cluster.arn
}

output "operador_access_key_id" {
  value = aws_iam_access_key.operador.id
}

output "operador_secret_access_key" {
  value     = aws_iam_access_key.operador.secret
  sensitive = true
}
