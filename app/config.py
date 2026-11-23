"""환경변수 설정. 값은 .env.example 참고."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    focus_stream_secret: str
    internal_api_key: str
    main_server_url: str
    time_source: str = "server"  # server | client
    feature_log_dir: str = ""

    @staticmethod
    def from_env() -> "Settings":
        secret = os.getenv("FOCUS_STREAM_SECRET", "")
        if len(secret.encode()) < 32:
            raise RuntimeError("FOCUS_STREAM_SECRET는 32바이트 이상이어야 합니다.")
        time_source = os.getenv("TIME_SOURCE", "server")
        if time_source not in ("server", "client"):
            raise RuntimeError("TIME_SOURCE는 server 또는 client 입니다.")
        return Settings(
            focus_stream_secret=secret,
            internal_api_key=os.getenv("INTERNAL_API_KEY", ""),
            main_server_url=os.getenv("MAIN_SERVER_URL", "http://localhost:8080"),
            time_source=time_source,
            feature_log_dir=os.getenv("FEATURE_LOG_DIR", ""),
        )
