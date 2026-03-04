data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_vpc" "this" {
  cidr_block           = "10.50.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.project_name}-vpc"
  }
}

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.50.1.0/24"
  availability_zone       = "${var.region}a"
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-public-a"
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "${var.project_name}-public-rt"
  }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "server" {
  name        = "${var.project_name}-server-sg"
  description = "WalkingMate server security group"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_ingress_cidrs
  }

  ingress {
    description = "WalkingMate API"
    from_port   = var.app_port
    to_port     = var.app_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-server-sg"
  }
}

resource "aws_iam_role" "ec2_ssm_role" {
  name = "${var.project_name}-ec2-ssm-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2_ssm_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2_ssm_role.name
}

locals {
  user_data = <<-EOT
#!/bin/bash
set -e

dnf update -y
dnf install -y docker git curl amazon-ssm-agent ec2-instance-connect
systemctl enable docker
systemctl start docker
systemctl enable amazon-ssm-agent
systemctl restart amazon-ssm-agent

mkdir -p /opt/walkingmate /opt/walkingmate/Data /opt/walkingmate/temp /opt/walkingmate/haproxy /opt/walkingmate/mysql_data
chown -R ec2-user:ec2-user /opt/walkingmate
docker network create common >/dev/null 2>&1 || true

MYSQL_ROOT_PASSWORD='${var.mysql_root_password}'
MYSQL_DATABASE_INIT='${var.mysql_database_init}'
MYSQL_USER_INIT='${var.mysql_user_init}'
MYSQL_PASSWORD_INIT='${var.mysql_password_init}'

if ! docker ps -a --format '{{.Names}}' | grep -Fxq walkingmate_mysql; then
  docker run -d \
    --name walkingmate_mysql \
    --restart unless-stopped \
    --network common \
    -e MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD" \
    -e MYSQL_DATABASE="$MYSQL_DATABASE_INIT" \
    -e MYSQL_USER="$MYSQL_USER_INIT" \
    -e MYSQL_PASSWORD="$MYSQL_PASSWORD_INIT" \
    -v /opt/walkingmate/mysql_data:/var/lib/mysql \
    mysql:8.4
else
  docker start walkingmate_mysql >/dev/null 2>&1 || true
fi

# docker compose 플러그인이 없는 환경 대비(standalone 설치)
if [ ! -x /usr/local/bin/docker-compose ]; then
  curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
fi
EOT
}

resource "aws_instance" "server" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public_a.id
  vpc_security_group_ids      = [aws_security_group.server.id]
  associate_public_ip_address = true
  key_name                    = var.key_name
  iam_instance_profile        = aws_iam_instance_profile.ec2_profile.name
  user_data                   = local.user_data

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size
  }

  tags = {
    Name = "${var.project_name}-ec2"
  }
}

