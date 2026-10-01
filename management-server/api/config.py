"""TX3 Management Server - Configuration"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://tx3:tx3@localhost:5432/tx3_management"
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # Auth
    secret_key: str = "CHANGE-ME-IN-PRODUCTION-use-openssl-rand-hex-32"
    access_token_expire_minutes: int = 480  # 8 hours
    refresh_token_expire_days: int = 30
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Server
    host: str = "0.0.0.0"
    port: int = 8400
    debug: bool = False
    cors_origins: list[str] = ["*"]

    # WireGuard
    wg_subnet: str = "10.88.0.0/24"
    wg_server_ip: str = "10.88.0.1"
    wg_server_port: int = 51820
    wg_server_public_key: str = ""
    wg_server_endpoint: str = ""
    wg_interface: str = "wg0"
    wg_config_path: str = "/etc/wireguard/wg0.conf"

    # Provisioning
    provisioning_port: int = 8401
    bootstrap_token: str = "CHANGE-ME-bootstrap-token"

    # Heartbeat
    heartbeat_interval: int = 30
    offline_threshold: int = 90  # seconds without heartbeat -> offline

    # Telemetry
    telemetry_retention_days: int = 90

    # File storage
    file_storage_path: str = "/var/lib/tx3/storage"
    max_upload_size_gb: int = 100

    model_config = {"env_prefix": "TX3_", "env_file": ".env"}


settings = Settings()
