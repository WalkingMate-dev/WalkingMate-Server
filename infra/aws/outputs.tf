output "instance_id" {
  description = "EC2 인스턴스 ID"
  value       = aws_instance.server.id
}

output "public_ip" {
  description = "EC2 퍼블릭 IP"
  value       = aws_instance.server.public_ip
}

output "api_base_url" {
  description = "앱에서 사용할 API 주소"
  value       = "http://${aws_instance.server.public_ip}:${var.app_port}"
}
