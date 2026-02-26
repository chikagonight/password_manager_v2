import customtkinter as ctk


class RecordWindow(ctk.CTkToplevel):
    def __init__(self, parent, record, password_manager_app):
        super().__init__(parent)

        self.record = record
        self.password_manager_app = password_manager_app

        self.title(self.record["record_name"])
        self.geometry("500x300")
        self.minsize(500, 300)
        self.grid_columnconfigure(0, weight = 1)
        self.grid_columnconfigure(1, weight = 1)
        self.grid_columnconfigure(2, weight = 1)
        self.rowconfigure(0, weight = 1)
        self.rowconfigure(1, weight = 1)
        self.rowconfigure(2, weight = 1)
        self.rowconfigure(3, weight = 1)
        self.rowconfigure(4, weight = 1)

        self.transient(parent)  # привязка к родителю
        self.grab_set()  # делаем модальным
        self.center_window(parent)  # центрируем окно
        self.focus_force()  # фокус на окно
        self.lift()  # поднять поверх

        self.create_widgets()

    def create_widgets(self):
        self.record_window_frame = ctk.CTkFrame(self)
        self.record_window_frame.grid(row = 0, rowspan = 5, column = 0, columnspan = 3, pady = 0, padx = 0,
                                      sticky = "wens")
        self.record_window_frame.columnconfigure(0, weight = 4)
        self.record_window_frame.columnconfigure(1, weight = 1)
        self.record_window_frame.columnconfigure(2, weight = 1)
        self.record_window_frame.rowconfigure(0, weight = 0)
        self.record_window_frame.rowconfigure(1, weight = 0)
        self.record_window_frame.rowconfigure(2, weight = 0)
        self.record_window_frame.rowconfigure(3, weight = 0)
        self.record_window_frame.rowconfigure(4, weight = 1)

        self.service_name = ctk.CTkEntry(self.record_window_frame)
        self.service_name.insert(0, string = self.record["service_name"])
        self.service_name.configure(state = "readonly")
        self.service_name.grid(row = 0, column = 0, pady = 5, padx = 5, sticky = "wes")

        self.link_service = ctk.CTkEntry(self.record_window_frame)
        self.link_service.insert(0, string = self.record["url_link_service"])
        self.link_service.configure(state = "readonly")
        self.link_service.grid(row = 1, column = 0, pady = 5, padx = 5, sticky = "wens")

        self.login_service = ctk.CTkEntry(self.record_window_frame)
        self.login_service.insert(0, string = self.record["login"])
        self.login_service.configure(state = "readonly")
        self.login_service.grid(row = 2, column = 0, pady = 5, padx = 5, sticky = "wens")

        self.password_service = ctk.CTkEntry(self.record_window_frame)
        self.password_service.insert(0, string = self.record["password"])
        self.password_service.configure(state = "readonly")
        self.password_service.grid(row = 3, column = 0, pady = 5, padx = 5, sticky = "wens")

        self.note_service = ctk.CTkTextbox(self.record_window_frame, width = 50, height = 25, border_width = 2)
        self.note_service.insert("1.0", text = self.record["note"])
        self.note_service.configure(state = "disabled")
        self.note_service.grid(row = 4, rowspan = 5, column = 0, pady = 5, padx = 5, sticky = "wens")

        self.change_record_button = ctk.CTkButton(self.record_window_frame, text = "Изменить запись")
        self.change_record_button.grid(row = 0, column = 1, columnspan = 2, pady = (8, 5), padx = (0,5), sticky = "we")

        self.open_in_browser_button = ctk.CTkButton(self.record_window_frame, text = "Открыть в браузере")
        self.open_in_browser_button.grid(row = 1, column = 1, columnspan = 2, pady = 5, padx = (0,5), sticky = "we")

        self.copy_login_button = ctk.CTkButton(self.record_window_frame, text = "Копировать логин")
        self.copy_login_button.grid(row = 2, column = 1, columnspan = 2, pady = 5, padx = (0,5), sticky = "we")

        self.copy_password_button = ctk.CTkButton(self.record_window_frame, text = "Показать", width = 50)
        self.copy_password_button.grid(row = 3, column = 1, pady = 5, padx = (0,5), sticky = "wens")

        self.copy_password_button = ctk.CTkButton(self.record_window_frame, text = "Копировать", width = 50)
        self.copy_password_button.grid(row = 3, column = 2, pady = 5, padx = (0,5), sticky = "wens")

        self.delete_record_button = ctk.CTkButton(self.record_window_frame, text = "Удалить запись",
                                                  command = lambda id = self.record["ID"]:
                                                  self.password_manager_app.delete_record(id))
        self.delete_record_button.grid(row = 4, column = 1, columnspan = 2, pady = 5, padx = (0,5), sticky = "wes")

    def center_window(self, parent):
        self.update_idletasks()
        parent.update_idletasks()

        width = self.winfo_width()
        height = self.winfo_height()

        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        x = parent_x + (parent_width // 2) - (width // 2) - 50
        y = parent_y + (parent_height // 2) - (height // 2) - 50

        self.geometry(f"{500}x{300}+{x}+{y}")
