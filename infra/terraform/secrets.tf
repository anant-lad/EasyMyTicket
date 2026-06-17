# ── Application Secrets (values set manually after apply) ────────────────────
# After `terraform apply`, populate with:
#   aws secretsmanager put-secret-value \
#     --secret-id /ticketing/prod/groq-api-key \
#     --secret-string '{"api_key":"gsk_..."}'

resource "aws_secretsmanager_secret" "groq_api_key" {
  name                    = "/${var.project_name}/${var.environment}/groq-api-key"
  description             = "Groq LLM API key"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "openrouter_api_key" {
  name                    = "/${var.project_name}/${var.environment}/openrouter-api-key"
  description             = "OpenRouter API key (fallback LLM provider)"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "email_credentials" {
  name                    = "/${var.project_name}/${var.environment}/email-credentials"
  description             = "Gmail SMTP credentials for notifications"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "api_keys" {
  name                    = "/${var.project_name}/${var.environment}/api-keys"
  description             = "Platform API keys for authenticating clients (JSON array)"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

# DB credentials are managed by RDS itself via manage_master_user_password = true
# RDS will store them at: /rds!db-<id>/ticketing_admin automatically
