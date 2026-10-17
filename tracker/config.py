import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    data_dir: Path = Path(os.getenv('DATA_DIR', './data'))
    password: str = os.getenv('APP_PASSWORD', '')
    secret: str = os.getenv('APP_SECRET', '')
    production: bool = bool(os.getenv('RAILWAY_ENVIRONMENT') or os.getenv('PRODUCTION') == 'true')
    schedule: bool = os.getenv('SCHEDULE_ENABLED', 'true').lower() == 'true'
    hour: int = int(os.getenv('DAILY_HOUR', '8'))
    timezone: str = os.getenv('DAILY_TIMEZONE', 'America/New_York')
    start_date: str = os.getenv('START_DATE', '2027-06-01')
    ai_limit: int = int(os.getenv('CHATGPT_DAILY_LIMIT', '30'))
    publication_hour: int = int(os.getenv('PUBLICATION_HOUR', '18'))
    publication_minute: int = int(os.getenv('PUBLICATION_MINUTE', '30'))
    strict_cohort: bool = os.getenv('STRICT_2027_COHORT', 'false').lower() == 'true'
    collection_interval: int = int(os.getenv('COLLECTION_INTERVAL_HOURS', '2'))

    def prepare(self):
        if self.production and (len(self.password) < 12 or len(self.secret) < 32):
            raise RuntimeError('Set APP_PASSWORD (12+ characters) and APP_SECRET (32+ characters).')
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.secret:
            import secrets
            path = self.data_dir / '.secret'
            if not path.exists():
                path.write_text(secrets.token_urlsafe(48))
                path.chmod(0o600)
            self.secret = path.read_text().strip()
        if not 0 <= self.hour <= 23:
            raise ValueError('DAILY_HOUR must be between 0 and 23')
        if not 0<=self.publication_hour<=23 or not 0<=self.publication_minute<=59 or not 1<=self.collection_interval<=24:
            raise ValueError('Invalid publication cutoff or collection interval')
        from zoneinfo import ZoneInfo
        ZoneInfo(self.timezone)


config = Config()
