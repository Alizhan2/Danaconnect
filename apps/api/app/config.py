import base64
import binascii
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.blob_configuration import blob_store_identity


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True)

    environment: str = "development"
    database_url: str = Field(default="sqlite:///./danaconnect.db", repr=False)
    database_pool_mode: Literal["queue", "null"] = "queue"
    vercel: bool = False
    trusted_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"]
    demo_mode: bool = False
    auth_debug_code: bool = False
    auth_secret: str = Field(default="local-development-change-before-deployment", repr=False)
    session_days: int = Field(default=7, ge=1, le=30)
    cron_secret: str = Field(default="", repr=False)
    otp_minutes: int = Field(default=10, ge=1, le=15)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    email_provider: str = "none"
    email_from: str = ""
    resend_api_key: str = Field(default="", repr=False)
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_starttls: bool = True
    smtp_tls: bool = False
    outbox_encryption_key: str = Field(default="", repr=False)
    outbox_previous_encryption_keys: list[str] = Field(default_factory=list, repr=False)
    outbox_max_attempts: int = Field(default=5, ge=1, le=10)
    outbox_lease_seconds: int = Field(default=120, ge=60, le=600)
    admin_mfa_minutes: int = Field(default=5, ge=1, le=10)
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    google_redirect_uri: str = ""
    frontend_url: str = "http://localhost:3000"
    storage_provider: str = "local"
    blob_store_id: str = ""
    blob_read_write_token: str = Field(default="", repr=False)
    private_upload_dir: str = "./private_uploads"
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    s3_sse: str = "AES256"
    s3_kms_key_id: str = ""
    ai_enabled: bool = False
    ai_api_key: str = Field(default="", repr=False)
    ai_model: str = Field(default="gpt-4.1-mini", min_length=1, max_length=100)
    ai_daily_user_limit: int = Field(default=10, ge=1, le=100)
    ai_daily_global_limit: int = Field(default=100, ge=1, le=10000)
    ai_max_input_chars: int = Field(default=6000, ge=500, le=12000)
    ai_max_output_tokens: int = Field(default=1600, ge=300, le=3000)

    @model_validator(mode="after")
    def secure_configuration(self):
        # Marketplace Neon injects a standard PostgreSQL URL. Our installed
        # SQLAlchemy driver is psycopg, so make the driver explicit before use.
        for prefix in ("postgresql://", "postgres://"):
            if self.database_url.startswith(prefix):
                self.database_url = "postgresql+psycopg://" + self.database_url[len(prefix):]
                break
        if self.vercel:
            if self.environment != "production":
                raise ValueError("Vercel requires explicitly configured production settings")
            if self.upload_max_bytes > 3 * 1024 * 1024:
                raise ValueError("Vercel requires UPLOAD_MAX_BYTES no greater than 3145728")
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("ENVIRONMENT must be development, test or production")
        if self.email_provider not in {"none", "resend", "smtp", "console"}:
            raise ValueError("EMAIL_PROVIDER must be none, resend, smtp or console")
        if self.storage_provider not in {"none", "local", "s3", "blob"}:
            raise ValueError("STORAGE_PROVIDER must be none, local, s3 or blob")
        if self.storage_provider == "blob":
            identity = blob_store_identity(self.blob_store_id, self.blob_read_write_token)
            if identity is None:
                raise ValueError("Blob requires a valid BLOB_STORE_ID and matching server read-write token")
            self.blob_store_id = identity
        if self.s3_sse not in {"AES256", "aws:kms"}:
            raise ValueError("S3_SSE must be AES256 or aws:kms")
        if self.smtp_tls and self.smtp_starttls:
            raise ValueError("SMTP_TLS and SMTP_STARTTLS cannot both be enabled")
        for encryption_key in ([self.outbox_encryption_key] if self.outbox_encryption_key else []) + self.outbox_previous_encryption_keys:
            try:
                decoded_key = base64.b64decode(encryption_key.encode(), altchars=b"-_", validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("Outbox encryption keys must be valid Fernet keys") from None
            if len(decoded_key) != 32:
                raise ValueError("Outbox encryption keys must decode to 32 bytes")
        if self.environment == "production":
            if self.auth_debug_code or self.demo_mode:
                raise ValueError("Production forbids AUTH_DEBUG_CODE and DEMO_MODE")
            if len(self.auth_secret) < 32 or self.auth_secret == "local-development-change-before-deployment":
                raise ValueError("Production requires a unique AUTH_SECRET of at least 32 characters")
            if not self.trusted_origins or any(not origin.startswith("https://") for origin in self.trusted_origins):
                raise ValueError("Production requires HTTPS TRUSTED_ORIGINS")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL DATABASE_URL")
            if self.email_provider == "console":
                raise ValueError("Production forbids console email delivery")
            if not self.outbox_encryption_key:
                raise ValueError("Production requires OUTBOX_ENCRYPTION_KEY")
            if not self.frontend_url.startswith("https://"):
                raise ValueError("Production requires HTTPS FRONTEND_URL")
            if self.google_redirect_uri and not self.google_redirect_uri.startswith("https://"):
                raise ValueError("Production requires HTTPS GOOGLE_REDIRECT_URI")
            if self.storage_provider == "local":
                raise ValueError("Production requires private object storage instead of local files")
            if self.s3_endpoint_url and not self.s3_endpoint_url.startswith("https://"):
                raise ValueError("Production requires HTTPS S3_ENDPOINT_URL")
        return self


settings = Settings()
