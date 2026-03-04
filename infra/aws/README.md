# WalkingMate AWS 인프라

현재 Python 서버 코드 기준으로 배포용 EC2를 생성하는 Terraform 구성입니다.
MySQL은 EC2 `user_data`에서 컨테이너를 생성/유지하고, 앱/워커 배포는 GitHub Actions(SSM)에서 수행합니다.

## 실행
```powershell
cd C:\PortfolioProject\server\infra\aws
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

## 주의
- `terraform.tfvars`는 직접 생성해서 사용
- `terraform.tfvars`에 `mysql_root_password`, `mysql_password_init` 값을 반드시 설정
- MySQL(3306), Redis(6379)는 외부 오픈하지 않음

