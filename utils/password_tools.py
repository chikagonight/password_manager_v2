from __future__ import annotations

import secrets
import string

from password_safe.domain import MAX_GENERATED_PASSWORD_LENGTH as MAX_GENERATED_PASSWORD_LENGTH
from password_safe.domain import MIN_GENERATED_PASSWORD_LENGTH as MIN_GENERATED_PASSWORD_LENGTH

SPECIAL_CHARACTERS = "!@#$%&*+-_=.?"


class PasswordGenerator:
    def generate(self, length_password: int | str) -> str | None:
        try:
            length = int(length_password)
        except (TypeError, ValueError):
            return None
        if not MIN_GENERATED_PASSWORD_LENGTH <= length <= MAX_GENERATED_PASSWORD_LENGTH:
            return None

        groups = (string.ascii_lowercase, string.ascii_uppercase, string.digits, SPECIAL_CHARACTERS)
        characters = [secrets.choice(group) for group in groups]
        alphabet = "".join(groups)
        characters.extend(secrets.choice(alphabet) for _ in range(length - len(characters)))
        secrets.SystemRandom().shuffle(characters)
        return "".join(characters)
