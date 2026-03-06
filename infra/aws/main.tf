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

data "aws_caller_identity" "current" {}

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
    cidr_blocks = ["0.0.0.0/0"]
  }

  # API entry point used by Android app.
  ingress {
    description = "WalkingMate API"
    from_port   = var.app_port
    to_port     = var.app_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = var.mysql_ingress_cidrs
    content {
      description = "WalkingMate MySQL"
      from_port   = 3306
      to_port     = 3306
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
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

resource "aws_iam_role_policy" "ec2_s3_data_access" {
  name = "${var.project_name}-ec2-s3-data-access"
  role = aws_iam_role.ec2_ssm_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListDataBucket"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${local.s3_bucket_name}"
        ]
      },
      {
        Sid    = "ReadWriteDataBucketObjects"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "arn:aws:s3:::${local.s3_bucket_name}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2_ssm_role.name
}

locals {
  s3_bucket_name = "${var.project_name}-data-${data.aws_caller_identity.current.account_id}-${var.region}"

  user_data = <<-EOT
#!/bin/bash
set -euo pipefail

# Keep first boot minimal so SSM becomes stable quickly.
dnf install -y docker amazon-ssm-agent ec2-instance-connect
# docker compose를 향후 사용할 수 있도록 플러그인 설치(없어도 부팅 실패는 막음)
dnf install -y docker-compose-plugin || true
systemctl enable --now docker
systemctl enable --now amazon-ssm-agent

# Small swap to reduce OOM risk on tiny instance types.
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
fi

mkdir -p /opt/walkingmate /opt/walkingmate/Data /opt/walkingmate/temp /opt/walkingmate/mysql_data /opt/walkingmate/redis_data
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
    -p 3306:3306 \
    -e MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD" \
    -e MYSQL_DATABASE="$MYSQL_DATABASE_INIT" \
    -e MYSQL_USER="$MYSQL_USER_INIT" \
    -e MYSQL_PASSWORD="$MYSQL_PASSWORD_INIT" \
    -v /opt/walkingmate/mysql_data:/var/lib/mysql \
    mysql:8.4
else
  docker start walkingmate_mysql >/dev/null 2>&1 || true
fi

if ! docker ps -a --format '{{.Names}}' | grep -Fxq walkingmate_redis; then
  docker run -d \
    --name walkingmate_redis \
    --restart unless-stopped \
    --network common \
    -v /opt/walkingmate/redis_data:/data \
    redis:7-alpine
else
  docker start walkingmate_redis >/dev/null 2>&1 || true
fi

echo 'WM_BOOTSTRAP_READY' > /opt/walkingmate/bootstrap_ready
EOT
}

resource "aws_instance" "server" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public_a.id
  vpc_security_group_ids      = [aws_security_group.server.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.ec2_profile.name
  user_data                   = local.user_data

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size
  }

  # deploy.yml filters by Name=walkingmate-ec2 exactly.
  tags = {
    Name = "walkingmate-ec2"
  }
}
