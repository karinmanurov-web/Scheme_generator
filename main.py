import glob
import importlib.util
import json
import math
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import ezdxf
except ImportError:
    messagebox.showerror("Ошибка", "Библиотека ezdxf не установлена! Выполните: pip install ezdxf")
    sys.exit(1)


STAMP_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stamp_config.json")
NOTES_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes_config.json")

DEFAULT_SCHEME_NOTES = {
    "Свайный фундамент": [
        "Линейные размеры указаны в миллиметрах, высотные отметки - в метрах.",
        "Отклонения по высоте и в плане определены геодезическими приборами.",
        "Допустимые отклонения по СП 46.13330.2012 п. 8.9 табл. 5 - 50 мм.",
        "Съемка произведена тахеометром {instrument} (серийный №{instrument_serial}).",
        "Съемка произведена с пунктов ГРО: {survey_points}.",
        "Фактические координаты центров свай указаны до начала срубки оголовков."
    ],
    "Откосные стенки": [
        "В числителе указаны проектные размеры (черным цветом), в знаменателе - фактические (красным).",
        "Линейные размеры в мм, высотные отметки в метрах.",
        "Съемка выполнена геодезическим прибором {instrument}."
    ],
    "Подбетонка": [
        "Линейные размеры указаны в миллиметрах, высоты - в метрах.",
        "В числителе указаны проектные размеры (черным цветом), в знаменателе - фактические (красным).",
        "Съемка выполнена электронным тахеометром {instrument}.",
        "Система координат: {coord_system}. Система высот: {height_system}."
    ],
    "Пролетное строение": [
        "Линейные размеры указаны в миллиметрах, высотные отметки - в метрах.",
        "В числителе указаны проектные размеры (черным цветом), в знаменателе - фактические (красным).",
        "Съемка выполнена электронным тахеометром {instrument}.",
        "Система координат: {coord_system}. Система высот: {height_system}."
    ],
}
NOTE_FIELDS = [
    ("surveyor", "Геодезист / ФИО", ""),
    ("instrument", "Прибор / тахеометр", ""),
    ("instrument_serial", "Серийный номер прибора", ""),
    ("survey_points", "Пункты ГРО", ""),
    ("coord_system", "Система координат", ""),
    ("height_system", "Система высот", ""),
]


class RedirectStdout:
    """Перехватывает стандартный вывод (print) и направляет его в функцию логирования GUI."""
    def __init__(self, write_log_func):
        self.write_log_func = write_log_func
        self.buf = ""

    def write(self, msg):
        self.buf += msg
        if '\n' in self.buf:
            lines = self.buf.split('\n')
            for line in lines[:-1]:
                if line.strip():
                    self.write_log_func(line)
            self.buf = lines[-1]

    def flush(self):
        if self.buf.strip():
            self.write_log_func(self.buf)
            self.buf = ""


class AppGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Генератор исполнительных схем v7.0")
        self.geometry("1150x820")
        self.minsize(980, 680)

        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.configure(bg="#2d3748")

        self.input_file = ""
        self.output_dxf = ""

        self.plugins = {}
        self.preview_thread = None

        # Данные интерактивной таблицы вкладки "Дополнительно"
        self.current_table_rows = []
        self.table_row_widgets = []

        self.notes_config = {}
        self.note_field_vars = {}
        self.note_enabled_vars = {}
        self.note_text_vars = {}

        # Переменные полей штампа (ГОСТ 2.104)
        self.stamp_vars = {
            'doc_code': tk.StringVar(),       # Обозначение документа / Шифр
            'object_name': tk.StringVar(),    # Наименование объекта
            'doc_subtitle': tk.StringVar(),   # Наименование сооружения / Раздел
            'doc_title': tk.StringVar(),      # Наименование документа / чертежа
            'stage': tk.StringVar(),         # Стадия проектирования (П, Р, ИД)
            'sheet': tk.StringVar(),         # Лист
            'sheets_total': tk.StringVar(),  # Листов
            'company_name': tk.StringVar(),  # Сведения об организации
            'dev_name': tk.StringVar(),      # Разработал (ФИО)
            'check_name': tk.StringVar(),    # Проверил (ФИО)
            'norm_name': tk.StringVar(),     # Нормоконтроль (ФИО)
            'gip_name': tk.StringVar(),      # ГИП / Нач. участка (ФИО)
        }

        self.setup_styles()
        self.load_stamp_config()
        self.load_notes_config()
        self.create_widgets()
        self.load_plugins()

    def setup_styles(self):
        """Настройка стилей интерфейса."""
        bg_dark = "#2d3748"
        bg_card = "#1a202c"
        fg_light = "#f7fafc"

        self.style.configure("TFrame", background=bg_dark)
        self.style.configure("Card.TFrame", background=bg_card, relief="flat")

        self.style.configure("TNotebook", background=bg_dark, borderwidth=0)
        self.style.configure("TNotebook.Tab", background="#4a5568", foreground="#e2e8f0", padding=[20, 8], font=("Segoe UI", 10, "bold"))
        self.style.map("TNotebook.Tab", background=[("selected", "#3182ce")], foreground=[("selected", "#e2e8f0")])

        self.style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), background=bg_dark, foreground=fg_light)
        self.style.configure("FormLabel.TLabel", font=("Segoe UI", 9, "bold"), background=bg_card, foreground="#cbd5e0")

    def create_widgets(self):
        """Создание основных вкладок и элементов управления."""
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 1. Вкладка "Файл"
        self.tab_file = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_file, text=" Файл ")

        # 2. Вкладка "Штамп"
        self.tab_stamp = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_stamp, text=" Штамп ")

        # 3. Вкладка "Дополнительно"
        self.tab_extra = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_extra, text=" Дополнительно ")

        # 4. Вкладка "Примечания"
        self.tab_notes = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_notes, text=" Примечания ")

        self.build_tab_file()
        self.build_tab_stamp()
        self.build_tab_extra()
        self.build_tab_notes()

    # ==========================================================================
    # ВКЛАДКА "ФАЙЛ"
    # ==========================================================================
    def build_tab_file(self):
        main_pane = ttk.Frame(self.tab_file)
        main_pane.pack(fill=tk.BOTH, expand=True)

        left_panel = ttk.Frame(main_pane, width=380)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10))
        left_panel.pack_propagate(False)

        btn_frame = ttk.Frame(left_panel)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_import = tk.Button(
            btn_frame, text="Импорт", font=("Segoe UI", 10, "bold"),
            bg="#3182ce", fg="white", activebackground="#2b6cb0", activeforeground="white",
            relief=tk.FLAT, cursor="hand2", command=self.browse_input, width=15, height=2
        )
        self.btn_import.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))

        self.btn_export = tk.Button(
            btn_frame, text="Экспорт", font=("Segoe UI", 10, "bold"),
            bg="#38a169", fg="white", activebackground="#2f855a", activeforeground="white",
            relief=tk.FLAT, cursor="hand2", command=self.start_generation, width=15, height=2
        )
        self.btn_export.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(5, 0))

        scheme_frame = ttk.Frame(left_panel)
        scheme_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(scheme_frame, text="Схема исполнительной:", font=("Segoe UI", 9, "bold"), foreground="#cbd5e0", background="#2d3748").pack(anchor=tk.W, pady=(0, 4))
        self.combo_algo = ttk.Combobox(scheme_frame, state="readonly", font=("Segoe UI", 10))
        self.combo_algo.pack(fill=tk.X, ipady=4)
        self.combo_algo.bind("<<ComboboxSelected>>", self.on_scheme_selected)

        log_frame = ttk.Frame(left_panel)
        log_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(log_frame, text="<Окно логов>", font=("Segoe UI", 9, "bold"), foreground="#a0aec0", background="#2d3748").pack(anchor=tk.W, pady=(0, 4))

        log_container = tk.Frame(log_frame, bd=1, relief=tk.SOLID, bg="#0f172a")
        log_container.pack(fill=tk.BOTH, expand=True)

        self.txt_log = tk.Text(log_container, font=("Consolas", 9), wrap=tk.WORD, bg="#0f172a", fg="#38bdf8", relief=tk.FLAT, padx=8, pady=8)
        self.txt_log.pack(fill=tk.BOTH, side=tk.LEFT, expand=True)

        scrollbar = ttk.Scrollbar(log_container, command=self.txt_log.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.txt_log.config(yscrollcommand=scrollbar.set)

        right_panel = ttk.Frame(main_pane)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.preview_canvas = tk.Canvas(right_panel, bg="#1e1e1e", highlightthickness=1, highlightbackground="#4a5568")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)

        self.preview_lbl = tk.Label(
            self.preview_canvas,
            text="<Рендер чертежа, который появится только\nпосле импорта проекта>",
            bg="#1e1e1e", fg="#94a3b8", font=("Segoe UI", 11, "italic"), justify=tk.CENTER
        )
        self.preview_lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    # ==========================================================================
    # ВКЛАДКА "ШТАМП"
    # ==========================================================================
    def build_tab_stamp(self):
        main_pane = ttk.Frame(self.tab_stamp)
        main_pane.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_pane, width=420)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10))
        left_frame.pack_propagate(False)

        canvas_form = tk.Canvas(left_frame, bg="#2d3748", highlightthickness=0)
        scrollbar_form = ttk.Scrollbar(left_frame, orient="vertical", command=canvas_form.yview)
        form_inner = ttk.Frame(canvas_form)

        form_inner.bind("<Configure>", lambda e: canvas_form.configure(scrollregion=canvas_form.bbox("all")))
        canvas_form.create_window((0, 0), window=form_inner, anchor="nw")
        canvas_form.configure(yscrollcommand=scrollbar_form.set)

        canvas_form.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_form.pack(side=tk.RIGHT, fill=tk.Y)

        fields = [
            ("Обозначение документа (Шифр):", 'doc_code'),
            ("Наименование объекта:", 'object_name'),
            ("Наименование сооружения / Раздел:", 'doc_subtitle'),
            ("Наименование документа:", 'doc_title'),
            ("Стадия проектирования:", 'stage'),
            ("Номер листа:", 'sheet'),
            ("Всего листов:", 'sheets_total'),
            ("Наименование организации:", 'company_name'),
            ("Разработал (ФИО):", 'dev_name'),
            ("Проверил (ФИО):", 'check_name'),
            ("Нормоконтроль (ФИО):", 'norm_name'),
            ("ГИП / Нач. участка (ФИО):", 'gip_name'),
        ]

        for idx, (label_text, var_name) in enumerate(fields):
            lbl = ttk.Label(form_inner, text=label_text, font=("Segoe UI", 9, "bold"), foreground="#e2e8f0", background="#2d3748")
            lbl.grid(row=idx * 2, column=0, sticky=tk.W, pady=(6, 2))

            entry = ttk.Entry(form_inner, textvariable=self.stamp_vars[var_name], font=("Segoe UI", 9))
            entry.grid(row=idx * 2 + 1, column=0, sticky=tk.EW, pady=(0, 6), ipadx=4, ipady=3)
            entry.bind("<KeyRelease>", self.on_stamp_field_change)

        form_inner.columnconfigure(0, weight=1)

        btn_box = ttk.Frame(left_frame)
        btn_box.pack(fill=tk.X, pady=(10, 0))

        btn_save = tk.Button(
            btn_box, text="Сохранить", font=("Segoe UI", 9, "bold"),
            bg="#3182ce", fg="white", activebackground="#2b6cb0", activeforeground="white",
            relief=tk.FLAT, cursor="hand2", command=self.save_stamp_config
        )
        btn_save.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5), ipady=5)

        btn_clear = tk.Button(
            btn_box, text="Очистить", font=("Segoe UI", 9, "bold"),
            bg="#e53e3e", fg="white", activebackground="#c53030", activeforeground="white",
            relief=tk.FLAT, cursor="hand2", command=self.clear_stamp_fields
        )
        btn_clear.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(5, 0), ipady=5)

        right_frame = ttk.Frame(main_pane)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(right_frame, text="Схематичный рендер штампа (ГОСТ 2.104)", font=("Segoe UI", 10, "bold"), foreground="#cbd5e0", background="#2d3748").pack(anchor=tk.W, pady=(0, 5))

        self.stamp_canvas = tk.Canvas(right_frame, bg="#ffffff", highlightthickness=1, highlightbackground="#4a5568")
        self.stamp_canvas.pack(fill=tk.BOTH, expand=True)
        self.stamp_canvas.bind("<Configure>", lambda e: self.draw_gost_stamp_schematic())

    # ========================================================================
    # ВКЛАДКА "ПРИМЕЧАНИЯ"
    # ========================================================================
    def get_current_scheme_name(self):
        return self.combo_algo.get().strip() if hasattr(self, 'combo_algo') else ''

    def _default_notes_for_scheme(self, scheme):
        return [{"enabled": True, "text": text} for text in DEFAULT_SCHEME_NOTES.get(scheme, [])]

    def load_notes_config(self):
        self.notes_config = {}
        if os.path.exists(NOTES_CONFIG_FILE):
            try:
                with open(NOTES_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.notes_config = data
            except Exception as e:
                print(f"Ошибка чтения настроек примечаний: {e}")

    def save_notes_config(self):
        try:
            with open(NOTES_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.notes_config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения настроек примечаний: {e}")

    def _ensure_scheme_notes(self, scheme):
        if scheme not in self.notes_config or not isinstance(self.notes_config.get(scheme), dict):
            self.notes_config[scheme] = {"notes": self._default_notes_for_scheme(scheme), "fields": {key: default for key, _label, default in NOTE_FIELDS}}
        else:
            self.notes_config[scheme].setdefault("notes", self._default_notes_for_scheme(scheme))
            self.notes_config[scheme].setdefault("fields", {key: default for key, _label, default in NOTE_FIELDS})

    def build_tab_notes(self):
        self.refresh_notes_tab()

    def refresh_notes_tab(self):
        for child in self.tab_notes.winfo_children():
            child.destroy()
        scheme = self.get_current_scheme_name()
        if not scheme:
            ttk.Label(self.tab_notes, text="Выберите схему исполнительной на вкладке «Файл».", font=("Segoe UI", 11), foreground="#cbd5e0", background="#2d3748").pack(expand=True)
            return
        self._ensure_scheme_notes(scheme)
        cfg = self.notes_config[scheme]
        self.note_enabled_vars, self.note_text_vars, self.note_field_vars = {}, {}, {}

        header = ttk.Frame(self.tab_notes)
        header.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(header, text=f"Примечания для схемы: {scheme}", font=("Segoe UI", 12, "bold"), foreground="#f7fafc", background="#2d3748").pack(side=tk.LEFT)
        buttons = ttk.Frame(header); buttons.pack(side=tk.RIGHT)
        tk.Button(buttons, text="Сохранить", font=("Segoe UI", 9, "bold"), bg="#3182ce", fg="white", relief=tk.FLAT, command=self.save_current_notes).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(buttons, text="Сбросить эталон", font=("Segoe UI", 9, "bold"), bg="#718096", fg="white", relief=tk.FLAT, command=self.reset_current_notes).pack(side=tk.LEFT)

        body = ttk.Frame(self.tab_notes); body.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(body, width=700); left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10)); left.pack_propagate(False)
        ttk.Label(left, text="Состав примечаний", font=("Segoe UI", 10, "bold"), foreground="#e2e8f0", background="#2d3748").pack(anchor=tk.W, pady=(0, 6))
        canvas = tk.Canvas(left, bg="#1a202c", highlightthickness=0)
        scroll = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas); inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw"); canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for idx, item in enumerate(cfg.get("notes", [])):
            enabled = tk.BooleanVar(value=bool(item.get("enabled", True)))
            text_var = tk.StringVar(value=str(item.get("text", "")))
            self.note_enabled_vars[idx], self.note_text_vars[idx] = enabled, text_var
            row = tk.Frame(inner, bg="#1a202c"); row.pack(fill=tk.X, pady=3, padx=4)
            tk.Checkbutton(row, variable=enabled, bg="#1a202c", activebackground="#1a202c", selectcolor="#2d3748", relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 6))
            ttk.Label(row, text=f"{idx + 1}.", width=4, foreground="#a0aec0", background="#1a202c").pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=text_var, font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        right = ttk.Frame(body, width=320); right.pack(side=tk.RIGHT, fill=tk.Y); right.pack_propagate(False)
        ttk.Label(right, text="Данные для подстановки", font=("Segoe UI", 10, "bold"), foreground="#e2e8f0", background="#2d3748").pack(anchor=tk.W, pady=(0, 6))
        ttk.Label(right, text="Используйте в тексте {instrument}, {instrument_serial}, {survey_points}, {coord_system} и {height_system}.", wraplength=310, font=("Segoe UI", 8), foreground="#a0aec0", background="#2d3748").pack(anchor=tk.W, pady=(0, 8))
        for key, label, default in NOTE_FIELDS:
            var = tk.StringVar(value=str(cfg.get("fields", {}).get(key, default)))
            self.note_field_vars[key] = var
            ttk.Label(right, text=label, font=("Segoe UI", 9, "bold"), foreground="#cbd5e0", background="#2d3748").pack(anchor=tk.W, pady=(6, 2))
            ttk.Entry(right, textvariable=var, font=("Segoe UI", 9)).pack(fill=tk.X, ipady=3)

    def save_current_notes(self):
        scheme = self.get_current_scheme_name()
        if not scheme: return
        self._ensure_scheme_notes(scheme)
        self.notes_config[scheme] = {
            "notes": [{"enabled": bool(self.note_enabled_vars[i].get()), "text": self.note_text_vars[i].get()} for i in sorted(self.note_text_vars)],
            "fields": {key: var.get() for key, var in self.note_field_vars.items()}
        }
        self.save_notes_config()
        self.write_log(f"[ПРИМЕЧАНИЯ] Настройки сохранены для схемы: {scheme}")

    def reset_current_notes(self):
        scheme = self.get_current_scheme_name()
        if not scheme: return
        self.notes_config[scheme] = {"notes": self._default_notes_for_scheme(scheme), "fields": {key: default for key, _label, default in NOTE_FIELDS}}
        self.save_notes_config(); self.refresh_notes_tab()

    def get_notes_data(self):
        scheme = self.get_current_scheme_name()
        if not scheme: return {"notes": [], "fields": {}}
        self.save_current_notes()
        cfg = self.notes_config.get(scheme, {})
        fields = {key: str(value).strip() for key, value in cfg.get("fields", {}).items()}
        rendered = []
        for item in cfg.get("notes", []):
            if not item.get("enabled", True): continue
            text = str(item.get("text", "")).strip()
            if not text: continue
            for key, value in fields.items(): text = text.replace("{" + key + "}", value or "________________")
            rendered.append(text)
        return {"scheme": scheme, "notes": rendered, "fields": fields}

    # ==========================================================================
    # ВКЛАДКА "ДОПОЛНИТЕЛЬНО"
    # ==========================================================================
    def build_tab_extra(self):
        self.container_extra = ttk.Frame(self.tab_extra)
        self.container_extra.pack(fill=tk.BOTH, expand=True)
        self.refresh_extra_tab()

    def refresh_extra_tab(self):
        for child in self.container_extra.winfo_children():
            child.destroy()

        if not self.input_file or not os.path.exists(self.input_file):
            lbl = ttk.Label(
                self.container_extra, text="<Таблица появится только после импорта чертежа>",
                font=("Segoe UI", 13, "italic"), foreground="#a0aec0", background="#2d3748"
            )
            lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            return

        algo_name = self.combo_algo.get()
        if algo_name and algo_name in self.plugins:
            mod = self.plugins[algo_name]
            if hasattr(mod, 'generate_table_data'):
                self.current_table_rows = mod.generate_table_data(self.input_file)
            else:
                self.current_table_rows = []
        else:
            self.current_table_rows = []

        top_bar = ttk.Frame(self.container_extra)
        top_bar.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            top_bar, text="Исполнительная ведомость координат и отклонений",
            font=("Segoe UI", 11, "bold"), foreground="#f7fafc", background="#2d3748"
        ).pack(side=tk.LEFT)

        btn_export_csv = tk.Button(
            top_bar, text="Экспорт таблицы в CSV", font=("Segoe UI", 9, "bold"),
            bg="#38a169", fg="white", activebackground="#2f855a", activeforeground="white",
            relief=tk.FLAT, cursor="hand2", command=self.export_table_to_csv
        )
        btn_export_csv.pack(side=tk.RIGHT, padx=(5, 0))

        btn_recalc = tk.Button(
            top_bar, text="Пересчитать отклонения", font=("Segoe UI", 9, "bold"),
            bg="#3182ce", fg="white", activebackground="#2b6cb0", activeforeground="white",
            relief=tk.FLAT, cursor="hand2", command=self.recalculate_deviations
        )
        btn_recalc.pack(side=tk.RIGHT, padx=(0, 5))

        table_canvas = tk.Canvas(self.container_extra, bg="#1a202c", highlightthickness=1, highlightbackground="#4a5568")
        table_scrollbar_y = ttk.Scrollbar(self.container_extra, orient="vertical", command=table_canvas.yview)
        table_scrollbar_x = ttk.Scrollbar(self.container_extra, orient="horizontal", command=table_canvas.xview)
        table_inner = tk.Frame(table_canvas, bg="#1a202c")

        table_inner.bind("<Configure>", lambda e: table_canvas.configure(scrollregion=table_canvas.bbox("all")))
        table_canvas.create_window((0, 0), window=table_inner, anchor="nw")
        table_canvas.configure(yscrollcommand=table_scrollbar_y.set, xscrollcommand=table_scrollbar_x.set)

        table_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        table_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        table_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        headers = [
            ("№ точки", 8),
            ("X проект (м)", 14),
            ("Y проект (м)", 14),
            ("X факт (м)", 14),
            ("Y факт (м)", 14),
            ("dX (мм)", 10),
            ("dY (мм)", 10),
            ("Z проект (м)", 14),
            ("Z факт (м)", 14),
            ("dZ (мм)", 10),
            ("Допуск (мм)", 10),
        ]

        for col_idx, (h_title, h_width) in enumerate(headers):
            h_lbl = tk.Label(
                table_inner, text=h_title, font=("Segoe UI", 9, "bold"),
                bg="#2d3748", fg="#f7fafc", width=h_width, relief=tk.RAISED, bd=1, pady=6
            )
            h_lbl.grid(row=0, column=col_idx, sticky="nsew", padx=1, pady=1)

        self.table_row_widgets = []

        for row_idx, rdata in enumerate(self.current_table_rows, start=1):
            bg_color = "#2d3748" if row_idx % 2 == 0 else "#1a202c"

            lbl_id = tk.Label(table_inner, text=rdata.get('point_name', str(row_idx)), font=("Segoe UI", 9), bg=bg_color, fg="#f7fafc", bd=1, relief=tk.FLAT)
            lbl_id.grid(row=row_idx, column=0, sticky="nsew", padx=1, pady=1)

            var_xp = tk.StringVar(value=str(rdata.get('x_prj', '')))
            ent_xp = tk.Entry(table_inner, textvariable=var_xp, font=("Segoe UI", 9), bg="#0f172a", fg="#38bdf8", insertbackground="white", justify="center", width=14)
            ent_xp.grid(row=row_idx, column=1, sticky="nsew", padx=1, pady=1)

            var_yp = tk.StringVar(value=str(rdata.get('y_prj', '')))
            ent_yp = tk.Entry(table_inner, textvariable=var_yp, font=("Segoe UI", 9), bg="#0f172a", fg="#38bdf8", insertbackground="white", justify="center", width=14)
            ent_yp.grid(row=row_idx, column=2, sticky="nsew", padx=1, pady=1)

            lbl_xf = tk.Label(table_inner, text="", font=("Segoe UI", 9, "bold"), bg=bg_color, fg="#ef4444", bd=1, relief=tk.FLAT)
            lbl_xf.grid(row=row_idx, column=3, sticky="nsew", padx=1, pady=1)

            lbl_yf = tk.Label(table_inner, text="", font=("Segoe UI", 9, "bold"), bg=bg_color, fg="#ef4444", bd=1, relief=tk.FLAT)
            lbl_yf.grid(row=row_idx, column=4, sticky="nsew", padx=1, pady=1)

            lbl_dx = tk.Label(table_inner, text=str(rdata.get('dx_mm', 0)), font=("Segoe UI", 9), bg=bg_color, fg="#cbd5e0", bd=1, relief=tk.FLAT)
            lbl_dx.grid(row=row_idx, column=5, sticky="nsew", padx=1, pady=1)

            lbl_dy = tk.Label(table_inner, text=str(rdata.get('dy_mm', 0)), font=("Segoe UI", 9), bg=bg_color, fg="#cbd5e0", bd=1, relief=tk.FLAT)
            lbl_dy.grid(row=row_idx, column=6, sticky="nsew", padx=1, pady=1)

            var_zp = tk.StringVar(value=str(rdata.get('z_prj', '')))
            ent_zp = tk.Entry(table_inner, textvariable=var_zp, font=("Segoe UI", 9), bg="#0f172a", fg="#38bdf8", insertbackground="white", justify="center", width=14)
            ent_zp.grid(row=row_idx, column=7, sticky="nsew", padx=1, pady=1)

            lbl_zf = tk.Label(table_inner, text="", font=("Segoe UI", 9, "bold"), bg=bg_color, fg="#ef4444", bd=1, relief=tk.FLAT)
            lbl_zf.grid(row=row_idx, column=8, sticky="nsew", padx=1, pady=1)

            lbl_dz = tk.Label(table_inner, text=str(rdata.get('dz_mm', 0)), font=("Segoe UI", 9), bg=bg_color, fg="#cbd5e0", bd=1, relief=tk.FLAT)
            lbl_dz.grid(row=row_idx, column=9, sticky="nsew", padx=1, pady=1)

            lbl_tol = tk.Label(table_inner, text=str(rdata.get('tolerance_mm', 50)), font=("Segoe UI", 9), bg=bg_color, fg="#cbd5e0", bd=1, relief=tk.FLAT)
            lbl_tol.grid(row=row_idx, column=10, sticky="nsew", padx=1, pady=1)

            row_entry_data = {
                'var_xp': var_xp, 'var_yp': var_yp, 'var_zp': var_zp,
                'lbl_xf': lbl_xf, 'lbl_yf': lbl_yf, 'lbl_zf': lbl_zf,
                'dx_mm': rdata.get('dx_mm', 0),
                'dy_mm': rdata.get('dy_mm', 0),
                'dz_mm': rdata.get('dz_mm', 0),
                'point_name': rdata.get('point_name', str(row_idx)),
                'tolerance_mm': rdata.get('tolerance_mm', 50)
            }

            def make_update_fn(rd):
                def _update(event=None):
                    self.update_row_facts(rd)
                return _update

            fn = make_update_fn(row_entry_data)
            ent_xp.bind("<KeyRelease>", fn)
            ent_yp.bind("<KeyRelease>", fn)
            ent_zp.bind("<KeyRelease>", fn)

            fn()

            self.table_row_widgets.append(row_entry_data)

    def update_row_facts(self, rd):
        def _calc(proj_str, dev_mm):
            if not proj_str or not proj_str.strip():
                return ""
            try:
                v = float(proj_str.strip().replace(',', '.'))
                return f"{(v + dev_mm / 1000.0):.3f}"
            except ValueError:
                return ""

        rd['lbl_xf'].config(text=_calc(rd['var_xp'].get(), rd['dx_mm']))
        rd['lbl_yf'].config(text=_calc(rd['var_yp'].get(), rd['dy_mm']))
        rd['lbl_zf'].config(text=_calc(rd['var_zp'].get(), rd['dz_mm']))

    def recalculate_deviations(self):
        self.refresh_extra_tab()

    def export_table_to_csv(self):
        if not self.table_row_widgets:
            messagebox.showwarning("Внимание", "Нет данных таблицы для экспорта.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Сохранить ведомость координат в CSV",
            defaultextension=".csv",
            filetypes=[("Таблицы CSV", "*.csv")]
        )
        if file_path:
            try:
                with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f, delimiter=';')
                    writer.writerow(['№ точки', 'X проект', 'Y проект', 'X факт', 'Y факт', 'dX (мм)', 'dY (мм)', 'Z проект', 'Z факт', 'dZ (мм)', 'Допуск (мм)'])

                    for idx, rd in enumerate(self.table_row_widgets, start=1):
                        row_idx = idx + 1
                        xp = rd['var_xp'].get().strip()
                        yp = rd['var_yp'].get().strip()
                        zp = rd['var_zp'].get().strip()

                        xf = rd['lbl_xf'].cget('text') or f"=B{row_idx}+F{row_idx}/1000"
                        yf = rd['lbl_yf'].cget('text') or f"=C{row_idx}+G{row_idx}/1000"
                        zf = rd['lbl_zf'].cget('text') or f"=H{row_idx}+J{row_idx}/1000"

                        writer.writerow([
                            rd['point_name'],
                            xp,
                            yp,
                            xf,
                            yf,
                            rd['dx_mm'],
                            rd['dy_mm'],
                            zp,
                            zf,
                            rd['dz_mm'],
                            rd['tolerance_mm']
                        ])
                messagebox.showinfo("Успех", f"Ведомость успешно сохранена:\n{os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось сохранить CSV: {e}")

    def on_scheme_selected(self, event=None):
        self.refresh_notes_tab()
        if self.input_file:
            self.refresh_extra_tab()

    def get_table_data(self) -> list:
        """Извлекает актуальные значения интерактивной таблицы из вкладки 'Дополнительно'."""
        table_rows = []
        for rd in self.table_row_widgets:
            xp_str = rd['var_xp'].get().strip()
            yp_str = rd['var_yp'].get().strip()
            zp_str = rd['var_zp'].get().strip()

            table_rows.append({
                'point_name': rd['point_name'],
                'x_prj': xp_str,
                'y_prj': yp_str,
                'z_prj': zp_str,
                'x_fact': rd['lbl_xf'].cget('text'),
                'y_fact': rd['lbl_yf'].cget('text'),
                'z_fact': rd['lbl_zf'].cget('text'),
                'dx_mm': rd['dx_mm'],
                'dy_mm': rd['dy_mm'],
                'dz_mm': rd['dz_mm'],
                'tolerance_mm': rd['tolerance_mm'],
            })
        return table_rows

    def draw_gost_stamp_schematic(self):
        self.stamp_canvas.delete("all")

        cw = self.stamp_canvas.winfo_width()
        ch = self.stamp_canvas.winfo_height()

        if cw <= 10 or ch <= 10:
            return

        stamp_w_mm = 185.0
        stamp_h_mm = 55.0

        margin = 20.0
        scale = min((cw - margin * 2) / stamp_w_mm, (ch - margin * 2) / stamp_h_mm)
        scale = max(scale, 1.2)

        w_px = stamp_w_mm * scale
        h_px = stamp_h_mm * scale

        x0 = (cw - w_px) / 2.0
        y0 = (ch - h_px) / 2.0
        x1 = x0 + w_px
        y1 = y0 + h_px

        def mx(mm):
            return x0 + mm * scale

        def my(mm_b):
            return y1 - mm_b * scale

        self.stamp_canvas.create_rectangle(x0, y0, x1, y1, outline="#000000", width=2)
        self.stamp_canvas.create_line(mx(65), y0, mx(65), y1, fill="#000000", width=2)

        for ry in range(5, 55, 5):
            self.stamp_canvas.create_line(mx(0), my(ry), mx(65), my(ry), fill="#000000", width=1)

        for cx in [10, 20, 30, 40, 55]:
            self.stamp_canvas.create_line(mx(cx), my(55), mx(cx), my(30), fill="#000000", width=1)
            self.stamp_canvas.create_line(mx(cx), my(10), mx(cx), my(0), fill="#000000", width=1)

        self.stamp_canvas.create_line(mx(20), my(30), mx(20), my(10), fill="#000000", width=1)
        self.stamp_canvas.create_line(mx(40), my(30), mx(40), my(10), fill="#000000", width=1)
        self.stamp_canvas.create_line(mx(55), my(30), mx(55), my(10), fill="#000000", width=1)

        font_sm = ("Segoe UI", max(6, int(2.1 * scale)), "bold")

        self.stamp_canvas.create_text(mx(5), my(32.5), text="Изм.", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(15), my(32.5), text="Кол.уч", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(25), my(32.5), text="Лист", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(35), my(32.5), text="№ док.", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(47.5), my(32.5), text="Подп.", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(60), my(32.5), text="Дата", font=font_sm, fill="#4a5568")

        self.stamp_canvas.create_text(mx(10), my(27.5), text="Разраб.", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(10), my(22.5), text="Пров.", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(10), my(17.5), text="Н. контр.", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(10), my(12.5), text="ГИП", font=font_sm, fill="#4a5568")

        self.stamp_canvas.create_line(mx(65), my(45), mx(185), my(45), fill="#000000", width=1)
        self.stamp_canvas.create_line(mx(65), my(30), mx(185), my(30), fill="#000000", width=1)
        self.stamp_canvas.create_line(mx(65), my(15), mx(185), my(15), fill="#000000", width=1)

        self.stamp_canvas.create_line(mx(135), my(30), mx(135), my(0), fill="#000000", width=1)

        self.stamp_canvas.create_line(mx(135), my(25), mx(185), my(25), fill="#000000", width=1)
        self.stamp_canvas.create_line(mx(150), my(30), mx(150), my(15), fill="#000000", width=1)
        self.stamp_canvas.create_line(mx(165), my(30), mx(165), my(15), fill="#000000", width=1)

        self.stamp_canvas.create_text(mx(142.5), my(27.5), text="Стадия", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(157.5), my(27.5), text="Лист", font=font_sm, fill="#4a5568")
        self.stamp_canvas.create_text(mx(175), my(27.5), text="Листов", font=font_sm, fill="#4a5568")

        def draw_cell_text(text_val, cx_mm, cy_mm, max_w_mm, font_size=3.2, color="#1e3a8a", anchor="center"):
            if text_val and text_val.strip():
                clean_t = text_val.strip().replace('\\P', '\n').replace('\\p', '\n')
                f = ("Segoe UI", max(6, int(font_size * scale)), "bold")
                w_px = max_w_mm * scale - 4
                self.stamp_canvas.create_text(
                    mx(cx_mm), my(cy_mm),
                    text=clean_t,
                    font=f,
                    anchor=anchor,
                    fill=color,
                    width=max(int(w_px), 10),
                    justify="center"
                )

        draw_cell_text(self.stamp_vars['doc_code'].get(), 125, 50, 116, font_size=3.8)
        draw_cell_text(self.stamp_vars['object_name'].get(), 125, 37.5, 116, font_size=3.2)
        draw_cell_text(self.stamp_vars['doc_subtitle'].get(), 100, 22.5, 66, font_size=3.2)

        draw_cell_text(self.stamp_vars['stage'].get(), 142.5, 20, 13, font_size=3.5)
        draw_cell_text(self.stamp_vars['sheet'].get(), 157.5, 20, 13, font_size=3.5)
        draw_cell_text(self.stamp_vars['sheets_total'].get(), 175, 20, 18, font_size=3.5)

        draw_cell_text(self.stamp_vars['doc_title'].get(), 100, 7.5, 66, font_size=3.2)
        draw_cell_text(self.stamp_vars['company_name'].get(), 160, 7.5, 46, font_size=3.2)

        draw_cell_text(self.stamp_vars['dev_name'].get(), 30, 27.5, 18, font_size=2.5, anchor="center")
        draw_cell_text(self.stamp_vars['check_name'].get(), 30, 22.5, 18, font_size=2.5, anchor="center")
        draw_cell_text(self.stamp_vars['norm_name'].get(), 30, 17.5, 18, font_size=2.5, anchor="center")
        draw_cell_text(self.stamp_vars['gip_name'].get(), 30, 12.5, 18, font_size=2.5, anchor="center")

    def on_stamp_field_change(self, event=None):
        self.draw_gost_stamp_schematic()
        self.save_stamp_config()

    def save_stamp_config(self):
        try:
            data = {k: v.get() for k, v in self.stamp_vars.items()}
            with open(STAMP_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения штампа: {e}")

    def load_stamp_config(self):
        if os.path.exists(STAMP_CONFIG_FILE):
            try:
                with open(STAMP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if k in self.stamp_vars:
                            self.stamp_vars[k].set(v)
            except Exception as e:
                print(f"Ошибка чтения конфигурации штампа: {e}")

    def clear_stamp_fields(self):
        for v in self.stamp_vars.values():
            v.set("")
        self.save_stamp_config()
        self.draw_gost_stamp_schematic()

    def get_stamp_data(self) -> dict:
        return {k: v.get().strip() for k, v in self.stamp_vars.items()}

    def load_plugins(self):
        self.plugins.clear()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if not current_dir:
            current_dir = "."

        search_pattern = os.path.join(current_dir, "algo_*.py")
        plugin_files = glob.glob(search_pattern)

        self.write_log(f"[ЯДРО] Поиск алгоритмов в {current_dir}...")

        for py_file in plugin_files:
            mod_name = os.path.basename(py_file)[:-3]
            if mod_name == "algo_stamp":
                continue
            try:
                spec = importlib.util.spec_from_file_location(mod_name, py_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                if hasattr(mod, 'ALGORITHM_NAME') and hasattr(mod, 'run'):
                    self.plugins[mod.ALGORITHM_NAME] = mod
                    self.write_log(f" + Подключен плагин: {mod.ALGORITHM_NAME}")
                else:
                    self.write_log(f" - Пропущен {mod_name}.py (отсутствует ALGORITHM_NAME или функция run)")
            except Exception as e:
                self.write_log(f" [ОШИБКА] Сбой загрузки плагина {mod_name}: {e}")

        algo_names = list(self.plugins.keys())
        if algo_names:
            self.combo_algo['values'] = algo_names
            self.combo_algo.current(0)
            self.refresh_notes_tab()
        else:
            self.write_log("[ВНИМАНИЕ] Не найдено ни одного плагина (файлы algo_*.py)!")

    def browse_input(self):
        path = filedialog.askopenfilename(title="Выберите исходный чертеж проекта", filetypes=[("Чертежи DXF", "*.dxf")])
        if path:
            self.input_file = os.path.normpath(path)
            self.write_log(f"[ИМПОРТ] Выбран исходник: {os.path.basename(self.input_file)}")

            self.trigger_dxf_preview()
            self.refresh_extra_tab()

    def write_log(self, text):
        def _append():
            self.txt_log.config(state=tk.NORMAL)
            self.txt_log.insert(tk.END, str(text) + "\n")
            self.txt_log.see(tk.END)
            self.txt_log.config(state=tk.DISABLED)
        self.after(0, _append)

    def trigger_dxf_preview(self):
        self.preview_lbl.config(text="Чтение геометрии чертежа...\nПожалуйста, подождите", fg="#fbbf24")
        self.preview_lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.preview_canvas.delete("geom")

        self.preview_canvas.update_idletasks()

        if self.preview_thread and self.preview_thread.is_alive():
            return

        self.preview_thread = threading.Thread(target=self._parse_and_render_dxf_task, args=(self.input_file,))
        self.preview_thread.daemon = True
        self.preview_thread.start()

    def _parse_and_render_dxf_task(self, filepath):
        try:
            doc = ezdxf.readfile(filepath)
            msp = doc.modelspace()

            lines = []
            max_entities = 50000
            count = 0

            def get_global_transform(lx, ly, ox, oy, scale, rot):
                lx *= scale
                ly *= scale
                if rot != 0.0:
                    rad = math.radians(rot)
                    nx = lx * math.cos(rad) - ly * math.sin(rad)
                    ny = lx * math.sin(rad) + ly * math.cos(rad)
                    lx, ly = nx, ny
                return lx + ox, ly + oy

            def extract_geom(entities, ox=0.0, oy=0.0, scale=1.0, rot=0.0):
                nonlocal count
                for ent in entities:
                    if count > max_entities:
                        return

                    dxftype = ent.dxftype()
                    if dxftype == 'LINE':
                        p1, p2 = ent.dxf.start, ent.dxf.end
                        x1, y1 = get_global_transform(p1.x, p1.y, ox, oy, scale, rot)
                        x2, y2 = get_global_transform(p2.x, p2.y, ox, oy, scale, rot)
                        lines.append((x1, y1, x2, y2))
                        count += 1

                    elif dxftype in ('LWPOLYLINE', 'POLYLINE'):
                        pts = list(ent.get_points('xy')) if dxftype == 'LWPOLYLINE' else [(v.dxf.location.x, v.dxf.location.y) for v in ent.vertices]
                        t_pts = [get_global_transform(p[0], p[1], ox, oy, scale, rot) for p in pts]
                        for i in range(len(t_pts) - 1):
                            lines.append((t_pts[i][0], t_pts[i][1], t_pts[i + 1][0], t_pts[i + 1][1]))
                            count += 1

                        is_closed = ent.closed if hasattr(ent, 'closed') else getattr(ent, 'is_closed', False)
                        if is_closed and len(t_pts) > 2:
                            lines.append((t_pts[-1][0], t_pts[-1][1], t_pts[0][0], t_pts[0][1]))
                            count += 1

                    elif dxftype == 'CIRCLE':
                        c = ent.dxf.center
                        r = ent.dxf.radius * abs(scale)
                        cx, cy = get_global_transform(c.x, c.y, ox, oy, scale, rot)
                        c_pts = [(cx + r * math.cos(math.pi / 4 * i), cy + r * math.sin(math.pi / 4 * i)) for i in range(9)]
                        for i in range(8):
                            lines.append((c_pts[i][0], c_pts[i][1], c_pts[i + 1][0], c_pts[i + 1][1]))
                        count += 8

                    elif dxftype == 'INSERT':
                        if ent.dxf.name in doc.blocks:
                            b_def = doc.blocks[ent.dxf.name]
                            ix, iy = ent.dxf.insert.x, ent.dxf.insert.y
                            i_scale = ent.dxf.xscale if ent.dxf.hasattr('xscale') else 1.0
                            i_rot = ent.dxf.rotation if ent.dxf.hasattr('rotation') else 0.0

                            gx, gy = get_global_transform(ix, iy, ox, oy, scale, rot)
                            g_scale = scale * i_scale
                            g_rot = rot + i_rot

                            extract_geom(b_def, gx, gy, g_scale, g_rot)

            extract_geom(msp)

            if not lines:
                self.after(0, lambda: self._show_preview_error("Геометрия не найдена\nили файл пуст"))
                return

            self.after(0, lambda: self._draw_lines_on_canvas(lines))

        except Exception as e:
            self.after(0, lambda err=str(e): self._show_preview_error(f"Ошибка чтения файла:\n{err}"))

    def _draw_lines_on_canvas(self, lines):
        self.preview_lbl.place_forget()
        self.preview_canvas.delete("all")

        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()

        if cw <= 1 or ch <= 1:
            cw, ch = 500, 500

        min_x = min(min(L[0], L[2]) for L in lines)
        max_x = max(max(L[0], L[2]) for L in lines)
        min_y = min(min(L[1], L[3]) for L in lines)
        max_y = max(max(L[1], L[3]) for L in lines)

        w = max_x - min_x
        h = max_y - min_y

        if w == 0 or h == 0:
            self._show_preview_error("Нулевые габариты чертежа")
            return

        scale = min(cw / w, ch / h) * 0.85

        offset_x = (cw - w * scale) / 2.0
        offset_y = (ch - h * scale) / 2.0

        for x1, y1, x2, y2 in lines:
            cx1 = (x1 - min_x) * scale + offset_x
            cy1 = ch - ((y1 - min_y) * scale + offset_y)
            cx2 = (x2 - min_x) * scale + offset_x
            cy2 = ch - ((y2 - min_y) * scale + offset_y)

            self.preview_canvas.create_line(cx1, cy1, cx2, cy2, fill="#0ea5e9", width=1, tags="geom")

    def _show_preview_error(self, text):
        self.preview_canvas.delete("all")
        self.preview_lbl.config(text=text, fg="#ef4444")
        self.preview_lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def start_generation(self):
        algo_name = self.combo_algo.get()
        if not algo_name or algo_name not in self.plugins:
            messagebox.showwarning("Внимание", "Пожалуйста, выберите схему исполнительной.")
            return
        if not self.input_file or not os.path.exists(self.input_file):
            messagebox.showwarning("Внимание", "Сначала выберите исходный DXF файл через кнопку 'Импорт'.")
            return

        dir_name = os.path.dirname(self.input_file)
        base_name = os.path.splitext(os.path.basename(self.input_file))[0]
        default_out = os.path.join(dir_name, f"{base_name}_ИСПОЛНИТЕЛЬНАЯ.dxf")

        save_path = filedialog.asksaveasfilename(
            title="Сохранить исполнительную схему (DXF)",
            initialfile=os.path.basename(default_out),
            initialdir=dir_name,
            defaultextension=".dxf",
            filetypes=[("Чертежи DXF", "*.dxf")]
        )

        if not save_path:
            return

        self.output_dxf = os.path.normpath(save_path)

        self.btn_export.config(state=tk.DISABLED, text="Обработка...")
        self.write_log(f"\n[ЭКСПОРТ] Инициализация алгоритма: {algo_name}")

        thread = threading.Thread(target=self.run_plugin_backend, args=(algo_name,))
        thread.daemon = True
        thread.start()

    def run_plugin_backend(self, algo_name):
        mod = self.plugins[algo_name]
        old_stdout = sys.stdout
        sys.stdout = RedirectStdout(self.write_log)

        stamp_data = self.get_stamp_data()
        stamp_data["_notes_data"] = self.get_notes_data()
        table_data = self.get_table_data()

        try:
            mod.run(
                input_dxf=self.input_file,
                output_dxf=self.output_dxf,
                output_csv=None,
                log_callback=self.write_log,
                stamp_data=stamp_data,
                table_data=table_data
            )
            self.after(0, self.on_success)
        except Exception as e:
            import traceback
            err_msg = traceback.format_exc()
            self.after(0, lambda: self.on_error(err_msg))
        finally:
            sys.stdout = old_stdout

    def on_success(self):
        self.btn_export.config(state=tk.NORMAL, text="Экспорт")
        self.write_log(f"[ГОТОВО] Исполнительный чертеж успешно сохранен: {os.path.basename(self.output_dxf)}")
        messagebox.showinfo("Успех", f"Исполнительный чертеж успешно создан!\n\nDXF: {os.path.basename(self.output_dxf)}")

    def on_error(self, err_msg):
        self.btn_export.config(state=tk.NORMAL, text="Экспорт")
        self.write_log(f"[КРИТИЧЕСКАЯ ОШИБКА] \n{err_msg}")
        messagebox.showerror("Ошибка выполнения", "Произошел сбой внутри алгоритма. Проверьте консоль логов для деталей.")


if __name__ == "__main__":
    app = AppGUI()
    app.mainloop()
