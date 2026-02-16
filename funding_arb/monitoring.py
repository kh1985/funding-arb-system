from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
from urllib import request


@dataclass
class AlertEvent:
    level: str
    title: str
    message: str
    context: Dict[str, str]


class WebhookNotifier:
    def __init__(self, webhook_url: Optional[str] = None, timeout_sec: int = 5):
        self.webhook_url = webhook_url
        self.timeout_sec = timeout_sec

    def send(self, event: AlertEvent) -> bool:
        if not self.webhook_url:
            return False

        body = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": event.level,
            "title": event.title,
            "message": event.message,
            "context": event.context,
        }
        payload = json.dumps(body).encode("utf-8")
        req = request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_sec) as resp:
            return 200 <= resp.status < 300
