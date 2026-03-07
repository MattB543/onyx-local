# FLI EC2 Instance - SSM Connection Guide

## Instance Details
- **Instance ID:** `i-0cd5ba2b366cd17a7`
- **Region:** `us-east-2`
- **Platform:** Amazon Linux 2023 (ARM/m7g.xlarge)
- **Private IP:** 172.31.24.165
- **VPC/Subnet:** vpc-02e7c85e1ca599015 / subnet-020556797df7ed459

## AWS Profile
Use profile `992382577718_EC2-Developer-SessionManager` from `~/.aws/credentials`.
These are temporary SSO session credentials - refresh from AWS SSO if expired.

## Connect via SSM

```bash
aws ssm start-session \
  --target i-0cd5ba2b366cd17a7 \
  --region us-east-2 \
  --profile "992382577718_EC2-Developer-SessionManager"
```

## Port Forwarding

Forward a remote port to localhost (e.g., Postgres 5432):

```bash
aws ssm start-session \
  --target i-0cd5ba2b366cd17a7 \
  --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=5432,localPortNumber=5432" \
  --region us-east-2 \
  --profile "992382577718_EC2-Developer-SessionManager"
```

## SSH Fallback

If you need SCP/SFTP/rsync, SSH is still available:

```bash
ssh -i "C:/Users/matth/projects/onyx-test/onyx-fli-key.pem" ec2-user@<public-ip>
```

Get current public IP:
```bash
aws ec2 describe-instances --instance-ids i-0cd5ba2b366cd17a7 \
  --region us-east-2 --profile "992382577718_EC2-Developer-SessionManager" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
```

## IAM Setup
- **Role:** `EC2-SSM-Role` with `AmazonSSMManagedInstanceCore` policy
- **Instance Profile:** `EC2-SSM-Role` (attached to instance)
