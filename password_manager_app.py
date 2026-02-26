import os.path
import time
from constants import RECORDS_FILE
from utils.records_file_tools import SaverRecordsInFile
from utils.file_tools import FileTools
from utils.settings_tools import SettingsTools
from utils.password_tools import PasswordGenerator
from utils.logger_tools import Logger
from password_manager_ui import Ui
from record_window import RecordWindow


class PasswordManagerApp:
    def __init__(self):
        self.file_tools = FileTools()
        self.records_file_tools = SaverRecordsInFile()
        self.settings_tools = SettingsTools()
        self.password_generator = PasswordGenerator()
        self.logger_tools = Logger()
        self.record_window = None
        self.create_records_cards = None
        if not self.file_tools.check_file_exist(RECORDS_FILE):
            self.logger_tools.log(f"Файл {RECORDS_FILE} не найден")
            self.file_tools.create_json_file(RECORDS_FILE)
            self.logger_tools.log(f"Создан новый {RECORDS_FILE}")
            time.sleep(1)
        self.id_arr = self.records_file_tools.load_ids()
        self.appearance_mode = self.settings_tools.load()

    def save_record(self, record_name, service_name, login, password, repeat_password, url_link_service, note):
        records_file = RECORDS_FILE
        if password == repeat_password:
            record = self.records_file_tools.get_record_object(record_name, service_name, login, password,
                                                               url_link_service, note)
            if self.file_tools.check_file_exist(records_file):
                if self.file_tools.check_file_empty(records_file):
                    self.records_file_tools.create_records_file(record, records_file)
                else:
                    self.records_file_tools.append_new_record(record, records_file)
            else:
                self.records_file_tools.create_records_file(record, records_file)

    def delete_record(self, record_id):
        record_file = self.records_file_tools.delete_record(record_id)
        self.file_tools.write_to_json_file(record_file, RECORDS_FILE)
        self.create_records_cards()
        self.record_window.destroy()

    def get_records(self, file) -> list:
        return self.records_file_tools.load(file)

    def password_generate(self, length_password) -> str:
        return self.password_generator.generate(length_password)

    def show_password_on_click(self, field, button):
        if field.cget("show") == "*":
            field.configure(show = "")
            button.configure(text = "Скрыть")
        else:
            field.configure(show = "*")
            button.configure(text = "Показать")


    def load_settings(self):
        return self.settings_tools.load()

    def save_settings(self, key, file_config, new_value, file):
        return self.settings_tools.save(key, file_config, new_value, file)

    def log_event(self, message: str):
        self.logger_tools.log(message)

    def open_window_record(self, parent, record):
        if self.record_window and self.record_window.winfo_exists():
            self.record_window.destroy()
        self.record_window = RecordWindow(parent = parent, record = record, password_manager_app = self)

    def import_records_from_csv(self, path_to_file):
        path_to_file = os.path.normpath(path_to_file)
        for row in self.file_tools.parse_csv_file(path_to_file):
            record = self.records_file_tools.get_record_object(
                record_name = row["name"],
                service_name = row["name"],
                login = row["username"],
                password = row["password"],
                url_link_service = row["url"],
                note = row["note"])
            self.records_file_tools.append_new_record(record, RECORDS_FILE)
            self.create_records_cards()


if __name__ == '__main__':
    password_manager_app = PasswordManagerApp()
    app = Ui(password_manager_app)
    app.mainloop()
