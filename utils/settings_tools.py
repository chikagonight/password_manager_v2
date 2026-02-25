from constants import SETTINGS_FILE, DEFAULT_SETTINGS
from utils.file_tools import FileTools


class SettingsTools:
    def __init__(self):
        self.file_tools = FileTools()

    def load(self):
        if self.file_tools.check_file_exist(SETTINGS_FILE):
            if self.file_tools.check_file_empty(SETTINGS_FILE):
                self.file_tools.write_to_json_file(DEFAULT_SETTINGS, SETTINGS_FILE)
        else:
            self.file_tools.write_to_json_file(DEFAULT_SETTINGS, SETTINGS_FILE)
        return self.file_tools.parse_json_file(SETTINGS_FILE)

    def save(self, key, file_config, new_value, file):
        self.load()
        file_config[key] = new_value
        self.file_tools.write_to_json_file(file_config, file)
