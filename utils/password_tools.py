import secrets, string

class PasswordGenerator:
    def __init__(self):
        pass

    def generate(self, length_password):
        length_password = int(length_password)
        if 5 < length_password < 30:
            symbols = string.digits + string.ascii_uppercase + string.ascii_lowercase + "!@#$%&*"
            output_password = ""
            for _ in range(length_password):
                output_password += secrets.choice(symbols)
            return output_password
        else:
            return None