# Componente A: clúster EKS emulado con Floci, con rol IAM de mínimo privilegio.

data "aws_caller_identity" "actual" {}
data "aws_partition" "actual" {}

locals {
  cuenta = data.aws_caller_identity.actual.account_id
  zonas  = ["${var.region}a", "${var.region}b"]
}

# ----------------------------------- red -----------------------------------
resource "aws_vpc" "eks" {
  cidr_block           = "10.30.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.cluster_name}-vpc" }
}

resource "aws_subnet" "eks" {
  count             = length(local.zonas)
  vpc_id            = aws_vpc.eks.id
  cidr_block        = cidrsubnet(aws_vpc.eks.cidr_block, 8, count.index)
  availability_zone = local.zonas[count.index]
  tags              = { Name = "${var.cluster_name}-${local.zonas[count.index]}" }
}

# ------------------------- rol del clúster (IAM) --------------------------
# Solo el servicio EKS de esta cuenta puede asumirlo (protección de "confused deputy").
data "aws_iam_policy_document" "confianza_eks" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.cuenta]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name                 = "${var.cluster_name}-cluster"
  description          = "Rol del plano de control EKS de Alertas y Notificaciones"
  assume_role_policy   = data.aws_iam_policy_document.confianza_eks.json
  max_session_duration = 3600
}

# Única política del rol: la administrada que AWS exige para el plano de control.
resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${data.aws_partition.actual.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

# --------------------------------- clúster ---------------------------------
resource "aws_eks_cluster" "this" {
  name     = var.cluster_name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids = aws_subnet.eks[*].id
  }

  access_config {
    authentication_mode = "API_AND_CONFIG_MAP"
  }

  depends_on = [aws_iam_role_policy_attachment.cluster]
}

# ------------------- operador: solo puede leer este clúster -------------------
# Identidad para `aws eks update-kubeconfig` / `get-token` (Floci no acepta test/test ahí).
resource "aws_iam_user" "operador" {
  name = "${var.cluster_name}-operador"
}

data "aws_iam_policy_document" "operador" {
  statement {
    sid       = "LeerEsteCluster"
    actions   = ["eks:DescribeCluster"]
    resources = [aws_eks_cluster.this.arn]
  }
}

resource "aws_iam_user_policy" "operador" {
  name   = "leer-cluster-${var.cluster_name}"
  user   = aws_iam_user.operador.name
  policy = data.aws_iam_policy_document.operador.json
}

resource "aws_iam_access_key" "operador" {
  user = aws_iam_user.operador.name
}
