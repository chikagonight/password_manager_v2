import customtkinter as ctk
from constants import *


class Ui(ctk.CTk):
    def __init__(self, password_manager_app):
        super().__init__()
        self.geometry("900x520")
        self.title("Password manager v2.1")
        ctk.FontManager.load_font("Segoe UI Emoji")
        self.password_manager_app = password_manager_app
        self.password_manager_app.create_records_cards = self.create_records_cards
        self.file_settings = self.password_manager_app.load_settings()
        ctk.set_default_color_theme("dark-blue")
        # ctk.set_appearance_mode(self.file_settings["theme"])
        ctk.set_appearance_mode(self.password_manager_app.appearance_mode["theme"])
        self.resizable(True, True)
        self.minsize(900, 520)
        self.grid_columnconfigure(0, weight = 1)
        self.grid_rowconfigure(0, weight = 1)
        self.create_input_tab()
        self.create_settings_tab()
        self.create_records_cards()

    # Функция создания области табов
    def create_input_tab(self):
        # Создаю экземпляр класса таб
        self.tabviews = ctk.CTkTabview(self, anchor = "w")
        self.tabviews.grid(row = 0, column = 0, padx = 0, pady = 0, sticky = "wens")

        # Создаю таб создания записи
        new_record_tabview = self.tabviews.add("Создать запись")
        # Растягивание по вертикали и горизонтали области таба в окне
        new_record_tabview.grid_columnconfigure(0, weight = 1)
        new_record_tabview.grid_columnconfigure(1, weight = 0)
        new_record_tabview.grid_columnconfigure(2, weight = 1)
        new_record_tabview.grid_columnconfigure(3, weight = 4)
        new_record_tabview.grid_rowconfigure(6, weight = 3)

        # Имя записи
        self.name_record_field = ctk.CTkEntry(new_record_tabview, placeholder_text = "Имя записи", state = "normal")
        self.name_record_field.grid(row = 0, column = 0, columnspan = 3, padx = 5, pady = 5, sticky = "wens")

        # Имя севиса
        self.name_service_field = ctk.CTkEntry(new_record_tabview, placeholder_text = "Имя сервиса", state = "normal")
        self.name_service_field.grid(row = 1, column = 0, columnspan = 1, padx = (5, 5), pady = 5, sticky = "wens")

        # Поле ввода ссылки
        self.url_input_field = ctk.CTkEntry(new_record_tabview, placeholder_text = "Ссылка url", state = "normal")
        self.url_input_field.grid(row = 1, column = 1, padx = (0, 5), pady = 5, sticky = "wens", columnspan = 2)

        # Указание логина
        self.login_input = ctk.CTkEntry(new_record_tabview, placeholder_text = "Логин", state = "normal")
        self.login_input.grid(row = 2, column = 0, padx = 5, pady = 5, sticky = "wen")

        # Строка ввода пароля
        self.password_input = ctk.CTkEntry(new_record_tabview, placeholder_text = "Пароль", show = "*",
                                           textvariable = None, state = "normal")
        self.password_input.grid(row = 3, column = 0, padx = 5, pady = 5, sticky = "wen")
        self.password_input.configure(takefocus = 1)  # Тестируем

        # Кнопка показать пароль
        self.show_password_button = ctk.CTkButton(new_record_tabview, text = "Показать", width = 30,
                                                  command = lambda:self.password_manager_app.show_password_on_click(
                                                      self.password_input, self.show_password_button))
        self.show_password_button.grid(row = 3, column = 1, padx = (0, 2.5), pady = 5, sticky = "wen")

    # Функция которая показывает/скрывает поле ввода пароля
    # def show_password_input(self):
    #     self.password_manager_app.show_password_on_click(self.password_input, self.show_password_button)
    #     # if self.password_input.cget("show") == "*":
    #     #     self.password_input.configure(show = "")
    #     #     self.show_password_button.configure(text = "Скрыть")
    #     # else:
    #     #     self.password_input.configure(show = "*")
    #     #     self.show_password_button.configure(text = "Показать")

        # Кнопка генерировать пароль
        self.gen_password_button = ctk.CTkButton(new_record_tabview, text = "Генерировать",
                                                 command = self.on_generate_password, width = 30)
        self.gen_password_button.grid(row = 3, column = 2, padx = (2.5, 5), pady = 5, sticky = "wen")

        # Указание длины пароля
        self.title_length_password = ctk.CTkLabel(new_record_tabview, text = "Длина пароля")
        self.title_length_password.grid(row = 4, column = 1, padx = (5, 5), pady = 2, sticky = "we")
        #
        config_length = [str(i) for i in range(8, 21)]
        self.length_password = ctk.CTkComboBox(new_record_tabview, values = config_length, width = 20, height = 25)
        self.length_password.grid(row = 4, column = 2, padx = (2.5, 5), pady = 5, sticky = "wens")

        # Поле повторения пароля
        self.repeat_password_input = ctk.CTkEntry(new_record_tabview, placeholder_text = "Повторить пароль",
                                                  show = "*", state = "normal")
        self.repeat_password_input.grid(row = 4, column = 0, padx = 5, pady = 5, sticky = "wen")

        # Поле ввода заметки
        self.note_field_title = ctk.CTkLabel(new_record_tabview, text = "Комментарий или заметка", state = "normal")
        self.note_field_title.grid(row = 5, column = 0, padx = 10, pady = 0, sticky = "w")
        #
        self.note_input_field = ctk.CTkTextbox(new_record_tabview, width = 300, height = 205, border_width = 2,
                                               bg_color = "#343638")
        self.note_input_field.grid(row = 6, column = 0, padx = 5, pady = (0, 5), sticky = "wens",
                                   columnspan = 3)

        # Поле поиска сохраненных паролей
        self.search_records_input = ctk.CTkEntry(new_record_tabview, placeholder_text = "Сохраненные пароли")
        self.search_records_input.grid(row = 0, column = 3, padx = (0, 60), pady = (5, 5), sticky = "wens")

        # Кнопка поиска записей
        self.search_records_button = ctk.CTkButton(new_record_tabview, text = "Поиск", width = 50)
        self.search_records_button.grid(row = 0, column = 3, padx = 5, pady = 5, sticky = "ens")

        # Поле вывода списка записей
        self.records_field = ctk.CTkScrollableFrame(new_record_tabview, scrollbar_button_color = "#1F538D",
                                                    scrollbar_button_hover_color = "#14375E", border_width = 2)
        self.records_field.grid(row = 1, column = 3, rowspan = 7, padx = (0, 5), pady = (0, 5), sticky = "wens")
        self.records_field.grid_rowconfigure(0, weight = 0)
        self.records_field.grid_columnconfigure(0, weight = 1)

        # Возможно стоит реализовать поиск таким образом:
        # Брать строку из поиска и искать по файлу в котором
        # будут храниться пароли и потом отображать в фрейме при помощи цикла
        # А не искать в уже отрисованых виджетах

        # Кнопка сохранения
        self.save_new_record_button = ctk.CTkButton(new_record_tabview, text = "Сохранить запись",
                                                    command = self.save_record)
        self.save_new_record_button.grid(row = 7, column = 0, columnspan = 3, padx = 5, pady = 5, sticky = "wens")

    def create_record_card(self, record, row_count):
        # Создаю карточку записи пароля
        self.frame_card_record = ctk.CTkFrame(self.records_field, border_width = 2)
        self.frame_card_record.grid(row = row_count, column = 0, padx = 1, pady = 1, sticky = "we")
        self.frame_card_record.grid_columnconfigure(0, weight = 1)
        self.frame_card_record.grid_columnconfigure(1, weight = 0)
        self.card_record_title = ctk.CTkLabel(self.frame_card_record, text = f"{record["record_name"]}")
        self.card_record_title.grid(row = 0, column = 0, padx = 10, pady = 5, sticky = "w")
        self.card_record_button = ctk.CTkButton(self.frame_card_record, text = "Открыть",
                                                command = lambda:self.password_manager_app.open_window_record(self, record))
        self.card_record_button.grid(row = 1, column = 1, padx = 5, pady = 5, sticky = "wens")
        return self.frame_card_record

    # Отображаю записи из records_json в фрейме - frame_cards_record
    def create_records_cards(self):
        self.refresh_records_field()
        row_count = 1
        for record in self.password_manager_app.get_records(RECORDS_FILE):
            row_count += 1
            self.frame_card_record = self.create_record_card(record, row_count)

    def refresh_records_field(self):
        for child in self.records_field.winfo_children():
            child.destroy()

        ##### ТАБ НАСТРОЕК #####

    def create_settings_tab(self):

        settings_tabview = self.tabviews.add("Настройки")
        settings_tabview.grid_rowconfigure(0, weight = 0)
        settings_tabview.grid_columnconfigure(0, weight = 3)
        settings_tabview.grid_columnconfigure(1, weight = 1)
        settings_tabview.grid_columnconfigure(2, weight = 3)

        # Настройка смены темы

        self.label_change_theme_switch = ctk.CTkLabel(settings_tabview, text = "Смена цветового оформления")
        self.label_change_theme_switch.grid(row = 0, column = 0, padx = 5, pady = 5, sticky = "wns")

        self.text_change_theme_switch = ""
        # Создаю селектор
        self.change_theme_switch = ctk.CTkSwitch(settings_tabview, text = self.text_change_theme_switch,
                                                 command = self.change_theme, onvalue = "Dark",
                                                 offvalue = "Light", state = "normal")
        self.change_theme_switch.grid(row = 0, column = 1, padx = 5, pady = 5, sticky = "wens")
        # Определяю положение кнопки смены темы исходя из значения в файле настроек
        if self.file_settings["theme"] == "Dark":
            self.change_theme_switch.select()
        else:
            self.change_theme_switch.deselect()

        # Настройка импорта паролей
        self.lable_path_to_csv_import_field = ctk.CTkLabel(settings_tabview, text = "Импортировать пароли из csv")
        self.lable_path_to_csv_import_field.grid(row = 1, column = 0, padx = 5, pady = 0, sticky = "wns")
        self.path_to_csv_import_field = ctk.CTkEntry(settings_tabview, placeholder_text = "Путь к csv файлу")
        self.path_to_csv_import_field.grid(row = 2, column = 0, padx = 5, pady = 5, sticky = "wens")

        self.import_records_button = ctk.CTkButton(settings_tabview, text = "Импорт",
                                                   command = self.get_string_from_import_field, width = 50)
        self.import_records_button.grid(row = 2, column = 1, padx = 5, pady = 5, sticky = "wns")

    def get_string_from_import_field(self):
        self.password_manager_app.import_records_from_csv(path_to_file = self.path_to_csv_import_field.get())

    ##### ФУНКЦИИ #####

    # функция которая вызывают хелпер для генерации паролей
    # передает в нею длину их поля comboBox
    def on_generate_password(self):
        password_length = int(self.length_password.get())
        output_password = self.password_manager_app.password_generate(password_length)
        if output_password:
            self.password_input.delete(0, "end")
            self.repeat_password_input.delete(0, "end")
            self.password_input.insert("end", output_password)
            self.repeat_password_input.insert("end", output_password)
            self.repeat_password_input.configure(show = "*")
            self.password_manager_app.log_event(
                f"Сгенерирован пароль длиной {self.length_password.get()} символов: {self.password_input.get()}")
        else:
            self.password_manager_app.log_event(f"Не корректная длина пароля - {password_length}")

    # Сохранение пароля в records.json
    def save_record(self):
        self.password_manager_app.save_record(
            self.name_record_field.get(),
            self.name_service_field.get(),
            self.login_input.get(),
            self.password_input.get(),
            self.repeat_password_input.get(),
            self.url_input_field.get(),
            self.note_input_field.get("1.0", "end"))
        # Очистка полей ввода после сохранения
        self.clear_input_fields()
        # Обновление фрейма с карточками записей
        self.create_records_cards()

    def clear_input_fields(self):
        self.name_record_field.delete(0, "end")
        self.name_service_field.delete(0, "end")
        self.login_input.delete(0, "end")
        self.password_input.delete(0, "end")
        self.repeat_password_input.delete(0, "end")
        self.url_input_field.delete(0, "end")
        self.note_input_field.delete("1.0", "end")

    # Функция для смены темы
    # Еще и сохраняет настройку в json
    def change_theme(self):
        ctk.set_appearance_mode(self.change_theme_switch.get())
        self.password_manager_app.save_settings("theme", self.file_settings, self.change_theme_switch.get(),
                                                SETTINGS_FILE)
