from pathlib import Path
import py_compile

# main.py
p = Path('main.py')
s = p.read_text(encoding='utf-8')
s = s.replace(
    'STAMP_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stamp_config.json")',
    '''STAMP_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stamp_config.json")
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
]'''
)
s = s.replace(
    '        # Переменные полей штампа (ГОСТ 2.104)',
    '        self.notes_config = {}\n        self.note_field_vars = {}\n        self.note_enabled_vars = {}\n        self.note_text_vars = {}\n\n        # Переменные полей штампа (ГОСТ 2.104)'
)
s = s.replace('        self.load_stamp_config()\n        self.create_widgets()', '        self.load_stamp_config()\n        self.load_notes_config()\n        self.create_widgets()')
s = s.replace(
    'self.style.map("TNotebook.Tab", background=[("selected", "#3182ce")], foreground=[("selected", "#ffffff")])',
    'self.style.map("TNotebook.Tab", background=[("selected", "#3182ce")], foreground=[("selected", "#e2e8f0")])'
)
s = s.replace(
    '        # 3. Вкладка "Дополнительно"\n        self.tab_extra = ttk.Frame(self.notebook, padding=10)\n        self.notebook.add(self.tab_extra, text=" Дополнительно ")\n\n        self.build_tab_file()\n        self.build_tab_stamp()\n        self.build_tab_extra()',
    '        # 3. Вкладка "Дополнительно"\n        self.tab_extra = ttk.Frame(self.notebook, padding=10)\n        self.notebook.add(self.tab_extra, text=" Дополнительно ")\n\n        # 4. Вкладка "Примечания"\n        self.tab_notes = ttk.Frame(self.notebook, padding=10)\n        self.notebook.add(self.tab_notes, text=" Примечания ")\n\n        self.build_tab_file()\n        self.build_tab_stamp()\n        self.build_tab_extra()\n        self.build_tab_notes()'
)
notes_block = r'''    # ========================================================================
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

'''
s = s.replace('    # ==========================================================================\n    # ВКЛАДКА "ДОПОЛНИТЕЛЬНО"', notes_block + '    # ==========================================================================\n    # ВКЛАДКА "ДОПОЛНИТЕЛЬНО"')
s = s.replace('    def on_scheme_selected(self, event=None):\n        if self.input_file:\n            self.refresh_extra_tab()', '    def on_scheme_selected(self, event=None):\n        self.refresh_notes_tab()\n        if self.input_file:\n            self.refresh_extra_tab()')
s = s.replace('            self.combo_algo.current(0)\n        else:', '            self.combo_algo.current(0)\n            self.refresh_notes_tab()\n        else:')
s = s.replace('        stamp_data = self.get_stamp_data()\n        table_data = self.get_table_data()', '        stamp_data = self.get_stamp_data()\n        stamp_data["_notes_data"] = self.get_notes_data()\n        table_data = self.get_table_data()')
p.write_text(s, encoding='utf-8')

# Plugin note rendering hooks.
p = Path('algo_piles.py'); s = p.read_text(encoding='utf-8')
s = s.replace('def draw_notes_and_legend(msp, x0: float, y0: float, scale: float = 1.0) -> float:', 'def draw_notes_and_legend(msp, x0: float, y0: float, scale: float = 1.0, custom_notes=None) -> float:')
s = s.replace('    for line in DEFAULT_NOTES:', '    for line in (custom_notes or DEFAULT_NOTES):')
s = s.replace('draw_notes_and_legend(msp_out, stamp_x0, stamp_y0 + 60.0 * global_scale, scale=global_scale)', 'draw_notes_and_legend(msp_out, stamp_x0, stamp_y0 + 60.0 * global_scale, scale=global_scale, custom_notes=((stamp_data or {}).get("_notes_data") or {}).get("notes"))')
p.write_text(s, encoding='utf-8')

p = Path('algo_walls.py'); s = p.read_text(encoding='utf-8')
s = s.replace('def draw_legend_and_notes(msp, start_pt: Tuple[float, float], scale: float = 1.0) -> None:', 'def draw_legend_and_notes(msp, start_pt: Tuple[float, float], scale: float = 1.0, custom_notes=None) -> None:')
s = s.replace('    notes = [\n        "1. В числителе указаны проектные размеры (черным цветом), в знаменателе - фактические (красным).",', '    notes = custom_notes or [\n        "1. В числителе указаны проектные размеры (черным цветом), в знаменателе - фактические (красным).",')
s = s.replace('draw_legend_and_notes(new_msp, start_pt=(stamp_x0, stamp_y0 + 60.0 * global_scale), scale=global_scale)', 'draw_legend_and_notes(new_msp, start_pt=(stamp_x0, stamp_y0 + 60.0 * global_scale), scale=global_scale, custom_notes=((stamp_data or {}).get("_notes_data") or {}).get("notes"))')
p.write_text(s, encoding='utf-8')

p = Path('algo_base.py'); s = p.read_text(encoding='utf-8')
s = s.replace('draw_notes(msp, stamp_x0, stamp_y0 + 65.0 * global_scale + 25.0 * global_scale, global_scale)', 'draw_notes(msp, stamp_x0, stamp_y0 + 65.0 * global_scale + 25.0 * global_scale, global_scale, custom_notes=((stamp_data or {}).get("_notes_data") or {}).get("notes"))')
p.write_text(s, encoding='utf-8')

p = Path('algo_bridge.py'); s = p.read_text(encoding='utf-8')
marker = 'def process_dxf_to_asbuilt_scheme(input_path: str, output_path: str, csv_path: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:'
if 'def draw_notes(msp, x_pos:' not in s:
    block = '''def draw_notes(msp, x_pos: float, y_pos: float, scale: float = 1.0, custom_notes=None) -> None:\n    notes = custom_notes or [\n        "Линейные размеры указаны в миллиметрах, высотные отметки - в метрах.",\n        "В числителе указаны проектные размеры (черным цветом), в знаменателе - фактические (красным).",\n        "Съемка выполнена электронным тахеометром.",\n        "Система координат и система высот принимаются по проектной документации."\n    ]\n    th = 2.5 * scale; step_y = 4.5 * scale\n    msp.add_text("ПРИМЕЧАНИЯ:", dxfattribs={"style": "ГОСТ_2.304", "height": 3.5 * scale, "layer": "ИСП_Текст", "color": COLOR_MAIN}).set_placement((x_pos, y_pos), align=TextEntityAlignment.BOTTOM_LEFT)\n    for i, note in enumerate(notes):\n        msp.add_text(note, dxfattribs={"style": "ГОСТ_2.304", "height": th, "layer": "ИСП_Текст", "color": COLOR_MAIN}).set_placement((x_pos, y_pos - (i + 1) * step_y), align=TextEntityAlignment.BOTTOM_LEFT)\n\n\n'''
    s = s.replace(marker, block + marker)
s = s.replace('draw_area_calc_table(out_msp, table_x + 50.0 * scale, table_y - 20.0 * scale, scale)', 'draw_area_calc_table(out_msp, table_x + 50.0 * scale, table_y - 20.0 * scale, scale)\n\n    stamp_x0 = in_x_max - 185.0 * scale\n    stamp_y0 = in_y_min\n    draw_notes(out_msp, stamp_x0, stamp_y0 + 65.0 * scale, scale, custom_notes=((stamp_data or {}).get("_notes_data") or {}).get("notes"))')
p.write_text(s, encoding='utf-8')

for name in ('main.py', 'algo_base.py', 'algo_bridge.py', 'algo_piles.py', 'algo_walls.py'):
    py_compile.compile(name, doraise=True)
