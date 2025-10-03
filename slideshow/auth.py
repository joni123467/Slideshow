"""Authentifizierung über PAM."""
from __future__ import annotations

import os
from dataclasses import dataclass

from flask_login import UserMixin
import simplepam


@dataclass
class User(UserMixin):
    username: str

    def get_id(self) -> str:
        return self.username


class PamAuthenticator:
    def __init__(self, service: str = "login"):
        self.service = service

    def authenticate(self, username: str, password: str) -> bool:
        if not username:
            return False
        return simplepam.authenticate(username, password, service=self.service)

    @staticmethod
    def default_user() -> str:
        return os.environ.get("USER", "pi")
