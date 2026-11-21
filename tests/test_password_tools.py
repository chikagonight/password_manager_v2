import string
import unittest

from utils.password_tools import MIN_GENERATED_PASSWORD_LENGTH, SPECIAL_CHARACTERS, PasswordGenerator


class PasswordGeneratorTests(unittest.TestCase):
    def test_generated_password_has_requested_length_and_every_character_group(self):
        password = PasswordGenerator().generate(32)

        self.assertEqual(32, len(password))
        self.assertTrue(any(character in string.ascii_lowercase for character in password))
        self.assertTrue(any(character in string.ascii_uppercase for character in password))
        self.assertTrue(any(character in string.digits for character in password))
        self.assertTrue(any(character in SPECIAL_CHARACTERS for character in password))

    def test_generator_rejects_out_of_range_length(self):
        generator = PasswordGenerator()

        self.assertIsNone(generator.generate(MIN_GENERATED_PASSWORD_LENGTH - 1))
        self.assertIsNone(generator.generate(129))

    def test_generator_accepts_eight_characters(self):
        password = PasswordGenerator().generate(8)

        self.assertEqual(8, len(password))


if __name__ == "__main__":
    unittest.main()
