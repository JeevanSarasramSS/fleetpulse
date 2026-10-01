# AWS reference stack: EKS + MSK (Kafka) + RDS Postgres + ElastiCache Redis.
# The app only consumes endpoints via the K8s Secret, so a GCP (GKE/Confluent/Cloud SQL/Memorystore)
# or Azure (AKS/Event Hubs Kafka/Flexible Server/Azure Cache) module can replace this with no code change.
terraform {
  required_version = ">= 1.6"
  required_providers { aws = { source = "hashicorp/aws", version = "~> 5.60" } }
}
provider "aws" { region = var.region }

variable "region"      { default = "ap-south-1" }   # Mumbai: data residency for Indian fleets (DPDP)
variable "name"        { default = "fleetpulse" }
variable "db_password" { sensitive = true }

module "vpc" {
  source             = "terraform-aws-modules/vpc/aws"
  version            = "~> 5.13"
  name               = var.name
  cidr               = "10.40.0.0/16"
  azs                = ["${var.region}a", "${var.region}b", "${var.region}c"]
  private_subnets    = ["10.40.1.0/24", "10.40.2.0/24", "10.40.3.0/24"]
  public_subnets     = ["10.40.101.0/24", "10.40.102.0/24", "10.40.103.0/24"]
  enable_nat_gateway = true
}

module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  version         = "~> 20.24"
  cluster_name    = var.name
  cluster_version = "1.30"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets
  eks_managed_node_groups = {
    default = { instance_types = ["c6i.xlarge"], min_size = 3, max_size = 12, desired_size = 3 }
  }
}

resource "aws_msk_cluster" "kafka" {
  cluster_name           = var.name
  kafka_version          = "3.6.0"
  number_of_broker_nodes = 3   # one per AZ, replication factor 3, min.insync.replicas 2
  broker_node_group_info {
    instance_type   = "kafka.m5.large"
    client_subnets  = module.vpc.private_subnets
    storage_info { ebs_storage_info { volume_size = 500 } }
  }
  encryption_info { encryption_in_transit { client_broker = "TLS" } }
}

resource "aws_db_subnet_group" "db" {
  name       = var.name
  subnet_ids = module.vpc.private_subnets
}

resource "aws_db_instance" "pg" {
  identifier              = var.name
  engine                  = "postgres"
  engine_version          = "16.4"
  instance_class          = "db.r6g.large"
  allocated_storage       = 200
  storage_encrypted       = true          # AES-256 at rest (KMS)
  multi_az                = true          # synchronous standby: CP for the relational core
  username                = "fleet"
  password                = var.db_password
  db_subnet_group_name    = aws_db_subnet_group.db.name
  backup_retention_period = 7
  skip_final_snapshot     = true
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = var.name
  description                = "fleetpulse hot state"
  node_type                  = "cache.r6g.large"
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = var.name
  subnet_ids = module.vpc.private_subnets
}

output "kafka_bootstrap" { value = aws_msk_cluster.kafka.bootstrap_brokers_tls }
output "pg_endpoint"     { value = aws_db_instance.pg.address }
output "redis_endpoint"  { value = aws_elasticache_replication_group.redis.primary_endpoint_address }
