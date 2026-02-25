import json, os, csv

class FileTools:
    def __init__(self):
        pass

    def check_file_exist(self, file):
        return os.path.exists(file)
        # if os.path.exists(file):
        #     return True
        # return False

    def check_file_empty(self, file):
        if os.path.getsize(file) == 0:
            return True
        return False

    def parse_json_file(self, file):
        with open(file, "r", encoding = "utf-8") as f:
            output_file = json.load(f)
        return output_file

    def write_to_json_file(self, what_to_write, file):
        with open(file, "w", encoding = "utf-8") as f:
            json.dump(what_to_write, f, ensure_ascii = False)

    def create_json_file(self, file):
        with open(file, "w", encoding = "utf-8") as f:
            json.dump([], f, ensure_ascii = False)

    def parse_csv_file(self, path_to_file):
        with open(path_to_file, "r", encoding = "utf-8") as f:
            return list(csv.DictReader(f))
        #     pass
        # return path_to_file
