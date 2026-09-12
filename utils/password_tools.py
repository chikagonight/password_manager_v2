from __future__ import annotations

import secrets
import string

MIN_GENERATED_PASSWORD_LENGTH = 12
MAX_GENERATED_PASSWORD_LENGTH = 128
SPECIAL_CHARACTERS = "!@#$%&*+-_=.?"


class PasswordGenerator:
    def generate(self, length_password: int | str) -> str | None:
        length = int(length_password)
        if not MIN_GENERATED_PASSWORD_LENGTH <= length <= MAX_GENERATED_PASSWORD_LENGTH:
            return None

        groups = (string.ascii_lowercase, string.ascii_uppercase, string.digits, SPECIAL_CHARACTERS)
        characters = [secrets.choice(group) for group in groups]
        alphabet = "".join(groups)
        characters.extend(secrets.choice(alphabet) for _ in range(length - len(characters)))
        secrets.SystemRandom().shuffle(characters)
        return "".join(characters)
