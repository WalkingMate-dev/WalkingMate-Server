variable "project_name" {
  description = "리소스 이름 접두사"
  type        = string
  default     = "walkingmate"
}

variable "region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "instance_type" {
  description = "EC2 인스턴스 타입"
  type        = string
  default     = "t3.micro"
}

variable "root_volume_size" {
  description = "EC2 루트 볼륨(GB)"
  type        = number
  default     = 25
}


variable "app_port" {
  description = "API 포트"
  type        = number
  default     = 18080
}

variable "key_name" {
  description = "EC2 Key Pair 이름"
  type        = string
  default     = null
}

variable "ssh_ingress_cidrs" {
  description = "SSH(22) 인바운드를 허용할 CIDR 목록 (예: [\"203.0.113.10/32\"])"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "mysql_root_password" {
  description = "MySQL root 비밀번호(user_data 부팅 초기화용)"
  type        = string
  sensitive   = true
}

variable "mysql_database_init" {
  description = "MySQL 초기 생성 데이터베이스명"
  type        = string
  default     = "walkingmate"
}

variable "mysql_user_init" {
  description = "MySQL 초기 생성 사용자명"
  type        = string
  default     = "walkingmate"
}

variable "mysql_password_init" {
  description = "MySQL 초기 생성 사용자 비밀번호(user_data 부팅 초기화용)"
  type        = string
  sensitive   = true
}
