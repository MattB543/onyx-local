EC2

Deploy Onyx on AWS EC2
Using AWS EC2 is the recommended way of deploying Onyx. It is simple to set up and should meet the performance needs of 90% of organizations looking to use Onyx!
​
Guide
1

Create an EC2 instance
Create an EC2 instance with the appropriate resources. For this guide, we will use the recommended m7g.xlarge instance.
Read our Resourcing guide for more details.

    Give your instance a descriptive name like onyx-prod
    Select the Amazon Linux 2023 AMI
    Select the 64-bit (Arm) architecture
    Select the m7g.xlarge instance type
    Select Allow HTTPS traffic from the internet in the Network settings section
    Configure storage following the Resourcing Guide

EC2 Instance CreationEC2 Security Group Configuration
2

Create the instance
Click Launch instance and then view your instance details.
Save the Public IPv4 address of the instance!
EC2 Public IPv4 Address
3

Point domain to the instance
If you don’t have a domain, buy one from a DNS provider like GoDaddy or just skip HTTPS for now.
To point our domain to the new instance, we need to add an A and CNAME record to our DNS provider.The A record should be the subdomain that you would like to use for the Onyx instance like prod.The CNAME record should be the same name with the www. in front resulting in www.prod pointing to the full domain like prod.onyx.app.DNS A Record ConfigurationDNS CNAME Record Configuration
4

Install Onyx requirements
Onyx requires git, docker, and docker compose.To install these on Amazon Linux 2023, run the following:

sudo yum update -y

sudo yum install docker -y
sudo service docker start

sudo curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

sudo yum install git

5

Install and Configure Onyx
To install Onyx, we’ll need to clone the repo and set the necessary environment variables.

git clone --depth 1 https://github.com/onyx-dot-app/onyx.git

cd onyx/deployment/docker_compose
cp env.prod.template .env
cp env.nginx.template .env.nginx

Fill out the .env and .env.nginx files.
.env

WEB_DOMAIN=<YOUR_DOMAIN> # Something like "onyx.app"

# If your email is something like "chris@onyx.app", then this should be "onyx.app"

# This prevents people outside your company from creating an account

VALID_EMAIL_DOMAINS=<YOUR_COMPANIES_EMAIL_DOMAIN>

# See our auth guides for options here

AUTH_TYPE=

.env.nginx

DOMAIN=<YOUR_DOMAIN> # Something like "onyx.app"

6

Launch Onyx
Running the init-letsencrypt.sh script will get us a SSL certificate from letsencrypt and launch the Onyx stack.

./init-letsencrypt.sh

You will hit an error if you fail the letsencrypt workflow more than 5 times. You will need to wait 72 hours or request a new domain.
If you are skipping the HTTPS setup, start Onyx manually:

docker compose -f docker-compose.prod.yml -p onyx-stack up -d --build --force-recreate

Give Onyx a few minutes to start up.You can monitor the progress with docker logs onyx-stack-api_server-1 -f.
You can access Onyx from the instance Public IPv4 or from the domain you set up earlier!

7

Enable secret encryption (recommended)
Configure KMS + SSM + IAM so Onyx encrypts secrets at rest (credentials, OAuth tokens, API keys).
Note: the `SECRET_ENCRYPTION_MODE=aws_kms_envelope` flow applies to OSS encryption paths.
EE encryption currently uses `ENCRYPTION_KEY_SECRET`.

Create a KMS key

Use an existing customer-managed key or create one:

aws kms create-key --description "Onyx secret encryption key" --region us-east-2

Store an encrypted data key in SSM Parameter Store

KMS_KEY_ID=<your-kms-key-id-or-arn>
AWS_REGION=us-east-2
SSM_PARAM=/onyx/prod/encrypted_dek/v1

# Returns a base64 CiphertextBlob that can be safely stored in SSM.
ENCRYPTED_DEK_B64=$(aws kms generate-data-key \
  --key-id "$KMS_KEY_ID" \
  --key-spec AES_256 \
  --query CiphertextBlob \
  --output text \
  --region "$AWS_REGION")

aws ssm put-parameter \
  --name "$SSM_PARAM" \
  --type SecureString \
  --value "$ENCRYPTED_DEK_B64" \
  --overwrite \
  --region "$AWS_REGION"

Create and attach an EC2 instance profile

Grant the instance role at least:

- `ssm:GetParameter` on the SSM parameter above
- `kms:Decrypt` on the KMS key above

Prefer using the instance profile instead of static `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

If your instance uses IMDSv2 (recommended), set EC2 metadata option `HttpPutResponseHopLimit` to at least `2`.
Docker bridge networking adds a hop, and a value of `1` can block containerized boto3 calls to IMDS.
Example:

aws ec2 modify-instance-metadata-options \
  --instance-id <your-instance-id> \
  --http-tokens required \
  --http-put-response-hop-limit 2 \
  --region us-east-2

Update `.env`

Add these settings:

SECRET_ENCRYPTION_MODE=aws_kms_envelope
SECRET_ENCRYPTION_REQUIRED=true
AWS_REGION_NAME=us-east-2
AWS_KMS_KEY_ID=<your-kms-key-id-or-arn>
AWS_ENCRYPTED_DEK_PARAM=/onyx/prod/encrypted_dek/v{version}
SECRET_KEY_VERSION=1
SECRET_OLD_KEY_VERSIONS=

Deploy and migrate

Take a DB snapshot/backup before running `--apply`.

Run migrations, then backfill old plaintext blobs:

docker compose -f docker-compose.prod.yml -p onyx-stack up -d --build --force-recreate
docker compose -f docker-compose.prod.yml -p onyx-stack exec -T api_server alembic upgrade head
docker compose -f docker-compose.prod.yml -p onyx-stack exec -T api_server python -m onyx.db.reencrypt_secret_values
docker compose -f docker-compose.prod.yml -p onyx-stack exec -T api_server python -m onyx.db.reencrypt_secret_values --apply

Finally restart `api_server` and `background` containers so both startup paths validate encryption readiness.
