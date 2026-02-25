import os.path
from constants import RECORDS_FILE
from utils.file_tools import FileTools


class SaverRecordsInFile:
    def __init__(self):
        self.file_tools = FileTools()
        self.records_file = RECORDS_FILE
        # self.id_records_generator()

    def get_record_object(self, record_name, service_name, login, password, url_link_service, note):
        id = self.id_records_generator(self.load_ids())
        record = {
            "ID"              : id,
            "record_name"     : record_name,
            "service_name"    : service_name,
            "login"           : login,
            "password"        : password,
            "url_link_service": url_link_service,
            "note"            : note
        }
        return record

    def append_new_record(self, record, file):
        if self.file_tools.check_file_exist(file):
            if self.file_tools.check_file_empty(file):
                self.create_records_file(record, file)
            else:
                records = self.file_tools.parse_json_file(file)
                records.insert(0, record)
                self.file_tools.write_to_json_file(records, file)
        else:
            self.create_records_file(record, file)

    def create_records_file(self, record, file):
        record = [record]
        self.file_tools.write_to_json_file(record, file)

    def load(self, file):
        if os.path.getsize(file) == 0:
            return []
        else:
            return self.file_tools.parse_json_file(file)

    def load_ids(self):
        id_arr = []
        if not self.file_tools.check_file_empty(self.records_file):
            record_file = self.file_tools.parse_json_file(self.records_file)
            for record in record_file:
                id_arr.append(record["ID"])
            return id_arr
        return id_arr

    def id_records_generator(self, id_arr):
        count = 0
        for i in range(len(id_arr)):
            if count not in id_arr:
                return count
            count += 1
        return count

    def delete_record(self, id):
        record_file = self.file_tools.parse_json_file(self.records_file)
        for record in record_file:
            if record["ID"] == id:
                print(record_file.index(record), id)
                record_file.pop(record_file.index(record))
                return record_file