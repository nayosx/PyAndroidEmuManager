#!/usr/bin/env python3
"""
Android Emulator Manager UI
- Android SDK only
- Compatible baseline for macOS, Linux and Windows
- Verifica rutas del SDK Android
- Lista AVDs disponibles
- Lanza un emulador seleccionado
- Muestra logs en vivo del proceso
- Permite crear nuevos AVDs usando avdmanager
"""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from services.avd_service import AvdInfo, AvdService, DeviceInfo, ImagePackageInfo
from services.config_store import ConfigStore
from services.process_runner import ProcessRunner
from services.sdk_paths import AndroidSdkPaths


class EmulatorManagerApp(tk.Tk):
    POLL_MS = 120
    CACHE_TTL_SECONDS = 600
    AVD_LIST_CACHE_TTL_SECONDS = 5
    APP_TITLE = "Android Emu Manager"

    def __init__(self) -> None:
        super().__init__()
        self.title(self.APP_TITLE)
        try:
            self.call("tk", "appname", self.APP_TITLE)
        except tk.TclError:
            pass
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.configure(bg="#0b1016")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.emulator_process: subprocess.Popen | None = None
        self.base_dir = Path(__file__).resolve().parent
        self.config_store = ConfigStore(self.base_dir / ".avd-manager.json")
        self.config: dict[str, object] = self.config_store.load()
        initial_sdk_root = str(self.config.get("sdk_root", AndroidSdkPaths.default_sdk_root()))
        self.runner = ProcessRunner(initial_sdk_root, self.log_queue)
        self.avd_service = AvdService(self.runner)

        self.android_sdk_root_var = tk.StringVar(value=initial_sdk_root)
        self.emulator_bin_var = tk.StringVar(value=str(self.config.get("emulator_path", "")))
        self.avdmanager_bin_var = tk.StringVar(value=str(self.config.get("avdmanager_path", "")))
        self.sdkmanager_bin_var = tk.StringVar(value=str(self.config.get("sdkmanager_path", "")))
        self.os_var = tk.StringVar(value=platform.system())

        self.selected_avd_var = tk.StringVar()
        self.create_name_var = tk.StringVar()
        self.create_package_var = tk.StringVar(
            value=str(self.config.get("last_image_package", self.avd_service.default_image_package()))
        )
        self.create_device_var = tk.StringVar(value=str(self.config.get("last_device_id", self.avd_service.default_device_id())))
        self.create_force_var = tk.BooleanVar(value=False)
        self.wipe_var = tk.BooleanVar(value=False)
        self.no_snapshot_var = tk.BooleanVar(value=False)
        self.no_boot_anim_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)
        self.window_icon_image: tk.PhotoImage | None = None
        self.header_logo_image: tk.PhotoImage | None = None
        self.images_cache: dict[tuple[str, str], list[str]] = {}
        self.images_cache_time: dict[tuple[str, str], float] = {}
        self.devices_cache: dict[tuple[str, str], list[DeviceInfo]] = {}
        self.devices_cache_time: dict[tuple[str, str], float] = {}
        self.avd_list_cache: dict[tuple[str, str], list[AvdInfo]] = {}
        self.avd_list_cache_time: dict[tuple[str, str], float] = {}
        self.avd_items: list[AvdInfo] = []
        self.avd_by_name: dict[str, AvdInfo] = {}
        self.deleting_avd_names: set[str] = set()
        self.log_entries: list[dict[str, str]] = []
        self.log_filter_var = tk.StringVar(value="all")
        self.log_expanded = False
        self.selected_avd_status_var = tk.StringVar(value="Selecciona un AVD para ver detalles.")
        self.selected_avd_meta_var = tk.StringVar(value="")
        self.env_summary_var = tk.StringVar(value="Detectando entorno Android SDK...")
        self.startup_status_var = tk.StringVar(value="Inicializando aplicación...")
        self.feedback_var = tk.StringVar(value="")
        self.feedback_clear_job: str | None = None
        self.env_status_ok = False
        self.startup_in_progress = False
        self.startup_state = "idle"

        self._setup_theme()
        self._apply_window_icon()
        self._load_persisted_caches()
        self._build_ui()
        self._fill_derived_paths_if_empty()
        self._register_var_traces()
        self.after(100, self._poll_log_queue)
        self.after(150, self._initial_load)

    def _initial_load(self) -> None:
        if self.startup_in_progress:
            return
        self.startup_in_progress = True
        self._set_startup_loading("Verificando entorno Android SDK...")
        self._append_log("[startup] Verificando rutas iniciales y cargando AVDs...\n")
        self._update_action_states()

        sdk_root = self.android_sdk_root_var.get().strip()
        emulator_path = self.emulator_bin_var.get().strip() or None
        avdmanager_path = self.avdmanager_bin_var.get().strip() or None
        sdkmanager_path = self.sdkmanager_bin_var.get().strip() or None

        def worker() -> None:
            try:
                status = self.avd_service.validate_environment(
                    sdk_root=sdk_root,
                    emulator_path=emulator_path,
                    avdmanager_path=avdmanager_path,
                    sdkmanager_path=sdkmanager_path,
                    deep=True,
                )

                avd_items: list[AvdInfo] = []
                list_error: str | None = None
                if status.emulator.usable:
                    self.after(0, lambda: self._set_startup_loading("Cargando AVDs..."))
                    code, loaded_items, _output = self.avd_service.list_avd_info(emulator_bin=status.emulator.path)
                    if code == 0:
                        avd_items = loaded_items
                    else:
                        list_error = "No se pudieron cargar los AVDs."

                self.after(0, lambda: self._complete_initial_load(status, avd_items, list_error))
            except Exception as exc:
                self.after(0, lambda: self._fail_initial_load(f"Error durante startup: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _set_startup_loading(self, message: str) -> None:
        self.startup_state = "loading"
        self.startup_status_var.set(message)
        self.startup_label.configure(style="Hint.TLabel")
        self.startup_progress.grid()
        self.startup_progress.start(8)

    def _set_startup_ready(self, message: str) -> None:
        self.startup_state = "ready"
        self.startup_status_var.set(message)
        self.startup_label.configure(style="Hint.TLabel")
        self.startup_progress.stop()
        self.startup_progress.grid_remove()

    def _set_startup_error(self, message: str) -> None:
        self.startup_state = "error"
        self.startup_status_var.set(message)
        self.startup_label.configure(style="ErrorHint.TLabel")
        self.startup_progress.stop()
        self.startup_progress.grid_remove()

    def _complete_initial_load(self, status, avd_items: list[AvdInfo], list_error: str | None) -> None:
        self.env_status_ok = status.is_ready or status.is_partial
        self.env_summary_var.set(status.summary)
        self.emulator_bin_var.set(status.emulator.path)
        self.avdmanager_bin_var.set(status.avdmanager.path)
        self.sdkmanager_bin_var.set(status.sdkmanager.path)
        self.save_config()

        if avd_items:
            cache_key = self._avd_list_cache_key()
            self.avd_list_cache[cache_key] = avd_items
            self.avd_list_cache_time[cache_key] = time.time()
        self.avd_items = avd_items
        self.avd_by_name = {item.name: item for item in avd_items}
        self._populate_avd_tree(avd_items)
        if avd_items:
            self.selected_avd_var.set(avd_items[0].name)
            self.avd_tree.selection_set(avd_items[0].name)
            self.avd_tree.focus(avd_items[0].name)
        else:
            self.selected_avd_var.set("")

        self.startup_in_progress = False
        if list_error:
            self._set_startup_error(list_error)
            self.show_feedback(list_error, error=True)
        elif status.is_ready or status.is_partial:
            count = len(avd_items)
            self._set_startup_ready(f"Entorno listo. {count} AVD(s) cargados.")
        else:
            self._set_startup_error(status.summary)
            self.show_feedback(status.summary, error=True)
        self._update_action_states()

    def _fail_initial_load(self, message: str) -> None:
        self.startup_in_progress = False
        self._set_startup_error(message)
        self.show_feedback(message, error=True)
        self._update_action_states()

    def _setup_theme(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("Root.TFrame", background="#0b1016")
        style.configure("Card.TFrame", background="#101721")
        style.configure("InnerCard.TFrame", background="#151d28")
        style.configure("TLabel", background="#101721", foreground="#dbe8ff")
        style.configure("Title.TLabel", background="#101721", foreground="#f7f9fc", font=("", 20, "bold"))
        style.configure("Subtitle.TLabel", background="#101721", foreground="#8ea2bf", font=("", 10))
        style.configure("SectionTitle.TLabel", background="#101721", foreground="#f0f5ff", font=("", 11, "bold"))
        style.configure("Hint.TLabel", background="#151d28", foreground="#8ea2bf")
        style.configure("ErrorHint.TLabel", background="#151d28", foreground="#ef8e8e")

        style.configure(
            "Dark.TEntry",
            fieldbackground="#151d28",
            foreground="#eff4fd",
            bordercolor="#2c3c50",
            lightcolor="#2c3c50",
            darkcolor="#2c3c50",
            insertcolor="#eff4fd",
            padding=(8, 6),
        )
        style.map("Dark.TEntry", fieldbackground=[("readonly", "#151d28")], foreground=[("readonly", "#eff4fd")])

        style.configure(
            "Primary.TButton",
            background="#3478f6",
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=0,
            padding=(12, 8),
        )
        style.map("Primary.TButton", background=[("active", "#2d6de1"), ("pressed", "#255bc2")])

        style.configure(
            "Neutral.TButton",
            background="#1a2532",
            foreground="#eff4fd",
            bordercolor="#33465e",
            lightcolor="#33465e",
            darkcolor="#33465e",
            padding=(12, 8),
        )
        style.map("Neutral.TButton", background=[("active", "#223246"), ("pressed", "#1a2738")])

        style.configure(
            "Danger.TButton",
            background="#b44b4b",
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=0,
            padding=(12, 8),
        )
        style.map("Danger.TButton", background=[("active", "#9d3f3f"), ("pressed", "#8a3434")])

        style.configure(
            "Success.TButton",
            background="#2e7d32",
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=0,
            padding=(12, 8),
        )
        style.map("Success.TButton", background=[("active", "#256427"), ("pressed", "#1b4d1e")])

        style.configure(
            "Card.TLabelframe",
            background="#101721",
            bordercolor="#273547",
            relief="solid",
            borderwidth=1,
            labeloutside=False,
        )
        style.configure("Card.TLabelframe.Label", background="#101721", foreground="#dbe8ff", font=("", 10, "bold"))
        style.configure(
            "Dark.Treeview",
            background="#0e131a",
            fieldbackground="#0e131a",
            foreground="#dbe8ff",
            bordercolor="#2a3a4e",
            borderwidth=1,
            rowheight=24,
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", "#2f4e7a")],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Dark.Treeview.Heading",
            background="#151d28",
            foreground="#dbe8ff",
            relief="flat",
            borderwidth=0,
            font=("", 10, "bold"),
        )

    def _load_png(self, name: str, subsample: int = 1) -> tk.PhotoImage | None:
        image_path = self.base_dir / name
        if not image_path.exists():
            return None
        image = tk.PhotoImage(file=str(image_path))
        if subsample > 1:
            image = image.subsample(subsample, subsample)
        return image

    def _apply_window_icon(self) -> None:
        icon = self._load_png("android.png")
        if icon is None:
            return
        self.window_icon_image = icon
        try:
            self.iconphoto(True, icon)
        except tk.TclError:
            return

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        header_shell = ttk.Frame(self, style="Root.TFrame", padding=(14, 14, 14, 10))
        header_shell.grid(row=0, column=0, sticky="ew")
        header_shell.columnconfigure(0, weight=1)

        header = ttk.Frame(header_shell, style="Card.TFrame", padding=(18, 14))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=1)

        title_row = ttk.Frame(header, style="Card.TFrame")
        title_row.grid(row=0, column=0, sticky="w")
        self.header_logo_image = self._load_png("android.png", subsample=8) or self.header_logo_image
        if self.header_logo_image is not None:
            ttk.Label(title_row, image=self.header_logo_image).grid(row=0, column=0, rowspan=2, padx=(0, 10))
        ttk.Label(title_row, text=self.APP_TITLE, style="Title.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(
            title_row,
            text="Una alternativa para manejar las AVD usando el SDK de Android",
            style="Subtitle.TLabel",
        ).grid(
            row=1, column=1, sticky="w", pady=(2, 10)
        )

        field_grid = ttk.Frame(header, style="Card.TFrame")
        field_grid.grid(row=2, column=0, columnspan=2, sticky="ew")
        field_grid.columnconfigure(0, weight=1)

        sdk_row = ttk.Frame(field_grid, style="Card.TFrame")
        sdk_row.grid(row=0, column=0, sticky="ew")
        sdk_row.columnconfigure(0, weight=1)
        ttk.Entry(sdk_row, textvariable=self.android_sdk_root_var, style="Dark.TEntry").grid(row=0, column=0, sticky="ew")
        self.sdk_refresh_button = ttk.Button(sdk_row, text="↻", command=self.verify_paths, style="Neutral.TButton", width=3)
        self.sdk_refresh_button.grid(row=0, column=1, padx=(8, 0))

        startup_row = ttk.Frame(field_grid, style="Card.TFrame")
        startup_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        startup_row.columnconfigure(0, weight=1)
        self.startup_label = ttk.Label(startup_row, textvariable=self.startup_status_var, style="Hint.TLabel")
        self.startup_label.grid(row=0, column=0, sticky="w")
        self.startup_progress = ttk.Progressbar(startup_row, mode="indeterminate", length=160)
        self.startup_progress.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.startup_progress.grid_remove()

        self.feedback_label = ttk.Label(field_grid, textvariable=self.feedback_var, style="Hint.TLabel")
        self.feedback_label.grid(row=2, column=0, sticky="w", pady=(4, 0))

        actions = ttk.Frame(header, style="Card.TFrame")
        actions.grid(row=0, column=1, sticky="ne")
        self.configs_button = ttk.Button(actions, text="Configs", command=self.open_configs_dialog, style="Neutral.TButton")
        self.configs_button.grid(row=0, column=0, padx=(8, 0))
        self.manage_images_button = ttk.Button(
            actions,
            text="Management Images",
            command=self.open_image_management_dialog,
            style="Neutral.TButton",
        )
        self.manage_images_button.grid(row=0, column=1, padx=(8, 0))
        self.create_header_button = ttk.Button(actions, text="Crear nuevo AVD", command=self.open_create_dialog, style="Primary.TButton")
        self.create_header_button.grid(row=0, column=2, padx=(8, 0))

        middle_shell = ttk.Frame(self, style="Root.TFrame", padding=(14, 0, 14, 10))
        middle_shell.grid(row=1, column=0, sticky="nsew")
        middle_shell.columnconfigure(0, weight=2)
        middle_shell.columnconfigure(1, weight=3)
        middle_shell.rowconfigure(0, weight=1)

        left = ttk.Frame(middle_shell, style="Card.TFrame", padding=14)
        right = ttk.Frame(middle_shell, style="Card.TFrame", padding=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_left_panel(left)
        self._build_right_panel(right)

        bottom_shell = ttk.Frame(self, style="Root.TFrame", padding=(14, 0, 14, 14))
        bottom_shell.grid(row=2, column=0, sticky="nsew")
        bottom_shell.columnconfigure(0, weight=1)
        bottom_shell.rowconfigure(0, weight=1)

        bottom = ttk.Frame(bottom_shell, style="Card.TFrame", padding=12)
        bottom.grid(row=0, column=0, sticky="nsew")
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(2, weight=1)

        self.log_toggle_button = ttk.Button(
            bottom,
            text="Log minimizado · Haz click para expandir u ocultar",
            command=self.toggle_log,
            style="Neutral.TButton",
        )
        self.log_toggle_button.grid(row=0, column=0, sticky="ew")

        self.log_toolbar = ttk.Frame(bottom, style="Card.TFrame")
        self.log_toolbar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.log_toolbar.columnconfigure(0, weight=1)
        ttk.Label(self.log_toolbar, text="Filtro", style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        self.log_filter_combo = ttk.Combobox(
            self.log_toolbar,
            values=("all", "create", "delete", "launch", "system"),
            textvariable=self.log_filter_var,
            state="readonly",
            width=14,
        )
        self.log_filter_combo.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.log_filter_combo.bind("<<ComboboxSelected>>", self._on_log_filter_change)
        self.log_clear_toolbar_button = ttk.Button(self.log_toolbar, text="Limpiar log", style="Neutral.TButton", command=self.clear_log)
        self.log_clear_toolbar_button.grid(row=0, column=2, sticky="e")
        self.log_text = scrolledtext.ScrolledText(
            bottom,
            wrap="word",
            height=16,
            bg="#0e131a",
            fg="#dbe8ff",
            insertbackground="#dbe8ff",
            selectbackground="#2f4e7a",
            relief="flat",
            borderwidth=0,
        )
        self.log_text.grid(row=2, column=0, sticky="nsew")
        self.log_text.configure(font=("Menlo", 11))
        if not self.log_expanded:
            self.log_toolbar.grid_remove()
            self.log_text.grid_remove()
        self._sync_log_toggle_label()

        self._append_log("Aplicación iniciada.\n")
        self._append_log("Enfoque: Android SDK solamente.\n")

    def _build_left_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        for r in range(3):
            parent.rowconfigure(r, weight=0)
        parent.rowconfigure(1, weight=1)

        ttk.Label(parent, text="AVDs disponibles", style="SectionTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.avd_tree = ttk.Treeview(
            parent,
            columns=("name", "device", "image", "ram", "heap", "data"),
            show="headings",
            style="Dark.Treeview",
            height=10,
            selectmode="browse",
        )
        self.avd_tree.heading("name", text="AVD")
        self.avd_tree.heading("device", text="Device")
        self.avd_tree.heading("image", text="Imagen")
        self.avd_tree.heading("ram", text="RAM")
        self.avd_tree.heading("heap", text="Heap")
        self.avd_tree.heading("data", text="Data")
        self.avd_tree.column("name", width=170, anchor="w")
        self.avd_tree.column("device", width=140, anchor="w")
        self.avd_tree.column("image", width=230, anchor="w")
        self.avd_tree.column("ram", width=70, anchor="center")
        self.avd_tree.column("heap", width=70, anchor="center")
        self.avd_tree.column("data", width=90, anchor="center")

        tree_frame = ttk.Frame(parent, style="Card.TFrame")
        tree_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 8))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.avd_tree.yview)
        self.avd_tree_scrollbar = tree_scroll
        self.avd_tree.configure(yscrollcommand=self._on_avd_tree_scroll)
        self.avd_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.avd_tree.bind("<<TreeviewSelect>>", self._on_avd_select)
        self.avd_tree.bind("<Double-1>", lambda _e: self.launch_emulator())

    def _build_right_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        ttk.Label(parent, text="AVD seleccionado", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        details = ttk.Frame(parent, style="InnerCard.TFrame", padding=12)
        details.grid(row=1, column=0, sticky="nsew")
        details.columnconfigure(0, weight=1)

        ttk.Label(details, textvariable=self.selected_avd_var, style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(details, textvariable=self.selected_avd_status_var, style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 4))
        ttk.Label(details, textvariable=self.selected_avd_meta_var, style="Hint.TLabel", justify="left").grid(row=2, column=0, sticky="w")

        action_row = ttk.Frame(details, style="InnerCard.TFrame")
        action_row.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        action_row.columnconfigure(0, weight=1)
        action_row.columnconfigure(1, weight=1)
        self.launch_button = ttk.Button(action_row, text="Lanzar", command=self.launch_emulator, style="Success.TButton")
        self.launch_button.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
        self.stop_button = ttk.Button(action_row, text="Detener", command=self.stop_emulator, style="Primary.TButton")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))
        self.edit_button = ttk.Button(action_row, text="Editar", command=self._edit_selected_avd, style="Neutral.TButton")
        self.edit_button.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.delete_button = ttk.Button(action_row, text="Eliminar", command=self._delete_selected_avd, style="Danger.TButton")
        self.delete_button.grid(row=1, column=1, sticky="ew", padx=(4, 0))

    # ---------------- Helpers ----------------

    def _register_var_traces(self) -> None:
        self.android_sdk_root_var.trace_add("write", self._on_path_fields_changed)
        self.emulator_bin_var.trace_add("write", self._on_path_fields_changed)
        self.avdmanager_bin_var.trace_add("write", self._on_path_fields_changed)
        self.sdkmanager_bin_var.trace_add("write", self._on_path_fields_changed)
        self.selected_avd_var.trace_add("write", self._on_selected_avd_changed)
        self.create_package_var.trace_add("write", self._on_create_defaults_changed)
        self.create_device_var.trace_add("write", self._on_create_defaults_changed)

    def _on_avd_tree_scroll(self, first: str, last: str) -> None:
        self.avd_tree_scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.avd_tree_scrollbar.grid_remove()
        else:
            self.avd_tree_scrollbar.grid()

    def _on_path_fields_changed(self, *_args) -> None:
        self._invalidate_avd_cache()
        self.save_config()

    def _on_create_defaults_changed(self, *_args) -> None:
        self.config["last_image_package"] = self.create_package_var.get().strip()
        self.config["last_device_id"] = self.create_device_var.get().strip()
        self.save_config()

    def _on_selected_avd_changed(self, *_args) -> None:
        self._refresh_selected_avd_details()
        self._update_action_states()

    def _refresh_selected_avd_details(self) -> None:
        selected = self.selected_avd_var.get().strip()
        item = self.avd_by_name.get(selected)
        if not item:
            self.selected_avd_status_var.set("Selecciona un AVD para ver detalles.")
            self.selected_avd_meta_var.set("")
            return
        status = "Eliminando..." if item.name in self.deleting_avd_names else ("Running" if item.is_running else item.status)
        self.selected_avd_status_var.set(status)
        ram = f"{item.ram_mb} MB" if item.ram_mb else "--"
        heap = f"{item.heap_mb} MB" if item.heap_mb else "--"
        data = item.data_partition or "--"
        device = item.device_name or "--"
        image = item.image_label or "--"
        self.selected_avd_meta_var.set(
            f"Device: {device}\nImagen: {image}\nRAM: {ram} · Heap: {heap} · Data: {data}"
        )

    def _images_cache_key(self) -> tuple[str, str]:
        return (self.android_sdk_root_var.get().strip(), self.sdkmanager_bin_var.get().strip())

    def _devices_cache_key(self) -> tuple[str, str]:
        return (self.android_sdk_root_var.get().strip(), self.avdmanager_bin_var.get().strip())

    def _avd_list_cache_key(self) -> tuple[str, str]:
        return (self.android_sdk_root_var.get().strip(), self.emulator_bin_var.get().strip())

    def _invalidate_avd_cache(self) -> None:
        self.avd_list_cache.clear()
        self.avd_list_cache_time.clear()
        self.avd_items = []
        self.avd_by_name = {}

    def _load_persisted_caches(self) -> None:
        now = time.time()

        raw_images_cache = self.config.get("images_cache", {})
        if isinstance(raw_images_cache, dict):
            for cache_key, payload in raw_images_cache.items():
                if not isinstance(cache_key, str) or not isinstance(payload, dict):
                    continue
                loaded_at = float(payload.get("loaded_at", 0) or 0)
                items = payload.get("items", [])
                if now - loaded_at > self.CACHE_TTL_SECONDS or not isinstance(items, list):
                    continue
                sdk_root, sdkmanager_path = cache_key.split("|", 1) if "|" in cache_key else (cache_key, "")
                self.images_cache[(sdk_root, sdkmanager_path)] = [str(item) for item in items]
                self.images_cache_time[(sdk_root, sdkmanager_path)] = loaded_at

        raw_devices_cache = self.config.get("devices_cache", {})
        if isinstance(raw_devices_cache, dict):
            for cache_key, payload in raw_devices_cache.items():
                if not isinstance(cache_key, str) or not isinstance(payload, dict):
                    continue
                loaded_at = float(payload.get("loaded_at", 0) or 0)
                items = payload.get("items", [])
                if now - loaded_at > self.CACHE_TTL_SECONDS or not isinstance(items, list):
                    continue
                sdk_root, avdmanager_path = cache_key.split("|", 1) if "|" in cache_key else (cache_key, "")
                parsed: list[DeviceInfo] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    parsed.append(
                        DeviceInfo(
                            device_id=str(item.get("device_id", "")),
                            name=str(item.get("name", "")),
                            oem=str(item.get("oem")) if item.get("oem") is not None else None,
                            tag=str(item.get("tag")) if item.get("tag") is not None else None,
                        )
                    )
                self.devices_cache[(sdk_root, avdmanager_path)] = parsed
                self.devices_cache_time[(sdk_root, avdmanager_path)] = loaded_at

    def save_config(self) -> None:
        serialized_images_cache: dict[str, dict[str, object]] = {}
        for (sdk_root, sdkmanager_path), items in self.images_cache.items():
            serialized_images_cache[f"{sdk_root}|{sdkmanager_path}"] = {
                "loaded_at": self.images_cache_time.get((sdk_root, sdkmanager_path), 0),
                "items": items,
            }

        serialized_devices_cache: dict[str, dict[str, object]] = {}
        for (sdk_root, avdmanager_path), items in self.devices_cache.items():
            serialized_devices_cache[f"{sdk_root}|{avdmanager_path}"] = {
                "loaded_at": self.devices_cache_time.get((sdk_root, avdmanager_path), 0),
                "items": [
                    {
                        "device_id": item.device_id,
                        "name": item.name,
                        "oem": item.oem,
                        "tag": item.tag,
                    }
                    for item in items
                ],
            }

        data: dict[str, object] = {
            "sdk_root": self.android_sdk_root_var.get().strip(),
            "emulator_path": self.emulator_bin_var.get().strip(),
            "avdmanager_path": self.avdmanager_bin_var.get().strip(),
            "sdkmanager_path": self.sdkmanager_bin_var.get().strip(),
            "last_image_package": self.create_package_var.get().strip(),
            "last_device_id": self.create_device_var.get().strip(),
            "log_expanded": bool(self.log_expanded),
            "images_cache": serialized_images_cache,
            "devices_cache": serialized_devices_cache,
        }
        self.config = data
        self.config_store.save(data)

    def _fill_derived_paths_if_empty(self) -> None:
        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        paths = self.avd_service.derived_paths()
        if not self.emulator_bin_var.get().strip():
            self.emulator_bin_var.set(paths["emulator"])
        if not self.avdmanager_bin_var.get().strip():
            self.avdmanager_bin_var.set(paths["avdmanager"])
        if not self.sdkmanager_bin_var.get().strip():
            self.sdkmanager_bin_var.set(paths["sdkmanager"])
        self.save_config()

    def _refresh_derived_paths(self) -> None:
        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        paths = self.avd_service.derived_paths()
        self.emulator_bin_var.set(paths["emulator"])
        self.avdmanager_bin_var.set(paths["avdmanager"])
        self.sdkmanager_bin_var.set(paths["sdkmanager"])
        self.validate_environment(deep=False)
        self._update_action_states()
        self.save_config()

    def validate_environment(self, deep: bool = False) -> None:
        status = self.avd_service.validate_environment(
            sdk_root=self.android_sdk_root_var.get().strip(),
            emulator_path=self.emulator_bin_var.get().strip() or None,
            avdmanager_path=self.avdmanager_bin_var.get().strip() or None,
            sdkmanager_path=self.sdkmanager_bin_var.get().strip() or None,
            deep=deep,
        )
        self.env_status_ok = status.is_ready or status.is_partial
        self.env_summary_var.set(status.summary)
        self.emulator_bin_var.set(status.emulator.path)
        self.avdmanager_bin_var.set(status.avdmanager.path)
        self.sdkmanager_bin_var.set(status.sdkmanager.path)
        self.save_config()

    def _update_action_states(self) -> None:
        if self.startup_in_progress:
            self.create_header_button.configure(state="disabled")
            self.manage_images_button.configure(state="disabled")
            self.configs_button.configure(state="normal")
            self.sdk_refresh_button.configure(state="disabled")
            self.launch_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
            self.edit_button.configure(state="disabled")
            self.delete_button.configure(state="disabled")
            return

        create_enabled = bool(self.env_status_ok)
        self.create_header_button.configure(state="normal" if create_enabled else "disabled")
        self.manage_images_button.configure(state="normal" if create_enabled else "disabled")
        self.configs_button.configure(state="normal")
        self.sdk_refresh_button.configure(state="normal")
        selected = self.selected_avd_var.get().strip()
        selected_item = self.avd_by_name.get(selected)
        is_deleting = selected in self.deleting_avd_names
        can_launch = bool(create_enabled and selected_item and not selected_item.is_running and not is_deleting)
        self.launch_button.configure(state="normal" if can_launch else "disabled")
        can_stop = bool(self.emulator_process and self.emulator_process.poll() is None)
        self.stop_button.configure(state="normal" if can_stop else "disabled")
        can_edit = bool(create_enabled and selected_item and not is_deleting)
        can_delete = bool(create_enabled and selected_item and not is_deleting)
        self.edit_button.configure(state="normal" if can_edit else "disabled")
        self.delete_button.configure(state="normal" if can_delete else "disabled")

    def autodetect_paths(self) -> None:
        self.android_sdk_root_var.set(AndroidSdkPaths.default_sdk_root())
        self.emulator_bin_var.set("")
        self.avdmanager_bin_var.set("")
        self.sdkmanager_bin_var.set("")
        self.images_cache.clear()
        self.devices_cache.clear()
        self.images_cache_time.clear()
        self.devices_cache_time.clear()
        self._invalidate_avd_cache()
        self._fill_derived_paths_if_empty()
        self.validate_environment(deep=True)
        self._update_action_states()
        self._append_log("[config] Rutas autodetectadas.\n")

    def reset_configuration(self) -> None:
        self.config = {}
        self.config_store.save({})
        self.android_sdk_root_var.set(AndroidSdkPaths.default_sdk_root())
        self.emulator_bin_var.set("")
        self.avdmanager_bin_var.set("")
        self.sdkmanager_bin_var.set("")
        self.create_package_var.set(self.avd_service.default_image_package())
        self.create_device_var.set(self.avd_service.default_device_id())
        self.images_cache.clear()
        self.devices_cache.clear()
        self.images_cache_time.clear()
        self.devices_cache_time.clear()
        self._invalidate_avd_cache()
        self._fill_derived_paths_if_empty()
        self.validate_environment(deep=True)
        self._update_action_states()
        self._append_log("[config] Configuración restablecida.\n")

    def _append_log(self, text: str) -> None:
        if not text:
            return
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self.log_entries.append(
            {
                "category": self._detect_log_category(text),
                "text": f"[{timestamp}] {text}",
            }
        )
        if len(self.log_entries) > 1500:
            self.log_entries = self.log_entries[-1500:]
        self._apply_log_view()

    def _detect_log_category(self, message: str) -> str:
        if "[create-avd]" in message:
            return "create"
        if "[delete-avd:" in message:
            return "delete"
        if "[launch:" in message:
            return "launch"
        return "system"

    def _apply_log_view(self) -> None:
        filter_value = self.log_filter_var.get().strip() or "all"
        visible_entries = self.log_entries
        if filter_value != "all":
            visible_entries = [entry for entry in self.log_entries if entry["category"] == filter_value]
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "".join(entry["text"] for entry in visible_entries[-500:]))
        self.log_text.see("end")

    def _on_log_filter_change(self, _event=None) -> None:
        self._apply_log_view()

    def toggle_log(self) -> None:
        self._set_log_expanded(not self.log_expanded, persist=True)

    def _set_log_expanded(self, expanded: bool, persist: bool = True) -> None:
        self.log_expanded = expanded
        if self.log_expanded:
            self.log_toolbar.grid()
            self.log_text.grid()
        else:
            self.log_toolbar.grid_remove()
            self.log_text.grid_remove()
        self._sync_log_toggle_label()
        if persist:
            self.config["log_expanded"] = self.log_expanded
            self.save_config()

    def _sync_log_toggle_label(self) -> None:
        if self.log_expanded:
            self.log_toggle_button.configure(text="Log expandido · Haz click para colapsar")
        else:
            self.log_toggle_button.configure(text="Log minimizado · Haz click para expandir")

    def open_configs_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Configuración")
        dialog.configure(bg="#101721")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("640x260")
        dialog.minsize(600, 240)
        dialog.columnconfigure(0, weight=1)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

        frame = ttk.Frame(dialog, style="Card.TFrame", padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Android SDK root").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.android_sdk_root_var, style="Dark.TEntry").grid(row=0, column=1, sticky="ew", pady=(0, 10))
        ttk.Label(frame, text="emulator").grid(row=1, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.emulator_bin_var, style="Dark.TEntry").grid(row=1, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(frame, text="avdmanager").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.avdmanager_bin_var, style="Dark.TEntry").grid(row=2, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(frame, text="sdkmanager").grid(row=3, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.sdkmanager_bin_var, style="Dark.TEntry").grid(row=3, column=1, sticky="ew", pady=(0, 10))

        action_row = ttk.Frame(frame, style="Card.TFrame")
        action_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(action_row, text="Autodetectar", style="Neutral.TButton", command=self.autodetect_paths).pack(side="left")
        ttk.Button(action_row, text="Restablecer", style="Neutral.TButton", command=self.reset_configuration).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="Verificar", style="Neutral.TButton", command=self.verify_paths).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="Cerrar", style="Primary.TButton", command=dialog.destroy).pack(side="right")

    def show_feedback(self, message: str, error: bool = False) -> None:
        prefix = "Error: " if error else "OK: "
        self.feedback_var.set(f"{prefix}{message}")
        if self.feedback_clear_job:
            self.after_cancel(self.feedback_clear_job)
        self.feedback_clear_job = self.after(4500, lambda: self.feedback_var.set(""))

    def clear_log(self) -> None:
        self.log_entries.clear()
        self._apply_log_view()

    def _poll_log_queue(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._poll_log_queue)

    def _on_avd_select(self, _event=None) -> None:
        selection = self.avd_tree.selection()
        if not selection:
            return
        name = selection[0]
        self.selected_avd_var.set(name)
        self._update_action_states()

    def _populate_avd_tree(self, items: list[AvdInfo]) -> None:
        self.avd_tree.delete(*self.avd_tree.get_children())
        for item in items:
            ram_text = f"{item.ram_mb} MB" if item.ram_mb else "--"
            heap_text = f"{item.heap_mb} MB" if item.heap_mb else "--"
            data_text = item.data_partition or "--"
            self.avd_tree.insert(
                "",
                "end",
                iid=item.name,
                values=(
                    item.name,
                    item.device_name or "--",
                    item.image_label or "--",
                    ram_text,
                    heap_text,
                    data_text,
                ),
            )

    def _build_env(self) -> dict[str, str]:
        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        return self.runner.build_env()

    def _run_sync(self, cmd: list[str], title: str) -> tuple[int, str]:
        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        return self.runner.run_sync(cmd, title)

    def _run_async(self, cmd: list[str], title: str, cwd: str | None = None) -> subprocess.Popen | None:
        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        return self.runner.run_async(cmd, title, cwd=cwd)

    # ---------------- Actions ----------------

    def verify_paths(self) -> None:
        self._append_log("\n[verify] Verificando rutas...\n")
        self.validate_environment(deep=True)
        self._update_action_states()
        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        report = self.avd_service.verify_paths()

        for check in report.checks:
            status = "OK" if check.exists else "MISSING"
            self._append_log(f"[verify] {check.label}: {check.path} -> {status}\n")

        avd_name = Path(self.avdmanager_bin_var.get()).name
        sdk_name = Path(self.sdkmanager_bin_var.get()).name
        self._append_log(f"[verify] which emulator -> {report.emulator_on_path}\n")
        self._append_log(f"[verify] which {avd_name} -> {report.avdmanager_on_path}\n")
        self._append_log(f"[verify] which {sdk_name} -> {report.sdkmanager_on_path}\n")

        self.list_avds(show_popup=False)

    def list_avds(self, show_popup: bool = False) -> None:
        emulator_bin = self.emulator_bin_var.get().strip()
        if not Path(emulator_bin).exists():
            messagebox.showerror("Ruta inválida", "No se encontró el binario emulator.")
            return

        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        cache_key = self._avd_list_cache_key()
        cache_time = self.avd_list_cache_time.get(cache_key, 0.0)
        if cache_key in self.avd_list_cache and (time.time() - cache_time) <= self.AVD_LIST_CACHE_TTL_SECONDS:
            avd_items = self.avd_list_cache[cache_key]
        else:
            code, avd_items, _output = self.avd_service.list_avd_info(emulator_bin=emulator_bin)
            if code != 0:
                messagebox.showerror("Error", "No se pudieron listar los AVDs. Revisa el log.")
                return
            self.avd_list_cache[cache_key] = avd_items
            self.avd_list_cache_time[cache_key] = time.time()

        self.avd_items = avd_items
        self.avd_by_name = {item.name: item for item in avd_items}
        selected = self.selected_avd_var.get().strip()
        self._populate_avd_tree(avd_items)
        if selected and selected in self.avd_by_name:
            self.avd_tree.selection_set(selected)
            self.avd_tree.focus(selected)
        elif avd_items:
            self.selected_avd_var.set(avd_items[0].name)
            self.avd_tree.selection_set(avd_items[0].name)
            self.avd_tree.focus(avd_items[0].name)
        else:
            self.selected_avd_var.set("")
        self._update_action_states()

        if show_popup:
            messagebox.showinfo("AVDs", f"Se encontraron {len(avd_items)} AVD(s).")

    def launch_emulator(self) -> None:
        if self.emulator_process and self.emulator_process.poll() is None:
            messagebox.showwarning("Emulador en ejecución", "Ya hay un emulador iniciado desde esta UI.")
            return

        emulator_bin = self.emulator_bin_var.get().strip()
        avd_name = self.selected_avd_var.get().strip()

        if not Path(emulator_bin).exists():
            messagebox.showerror("Ruta inválida", "No se encontró el binario emulator.")
            return
        if not avd_name:
            messagebox.showerror("AVD requerido", "Selecciona o escribe el nombre de un AVD.")
            return

        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        proc = self.avd_service.launch_emulator(
            avd_name=avd_name,
            emulator_bin=emulator_bin,
            wipe_data=self.wipe_var.get(),
            no_snapshot=self.no_snapshot_var.get(),
            no_boot_anim=self.no_boot_anim_var.get(),
            verbose=self.verbose_var.get(),
        )
        if proc is None:
            messagebox.showerror("Error", "No se pudo iniciar el emulador.")
            return

        self.emulator_process = proc
        self._append_log(f"[launch:{avd_name}] PID={proc.pid}\n")
        self._append_log(f"[launch:{avd_name}] Esperando salida del proceso...\n")
        self._update_action_states()
        self.save_config()

    def stop_emulator(self) -> None:
        proc = self.emulator_process
        if not proc or proc.poll() is not None:
            self._append_log("[stop] No hay emulador activo lanzado desde esta UI.\n")
            self._update_action_states()
            return

        try:
            self._append_log(f"[stop] Enviando señal de terminación a PID={proc.pid}\n")
            proc.terminate()
            try:
                proc.wait(timeout=8)
                self._append_log("[stop] Proceso terminado correctamente.\n")
            except subprocess.TimeoutExpired:
                self._append_log("[stop] Terminación lenta. Enviando kill.\n")
                proc.kill()
        except Exception as exc:
            self._append_log(f"[stop] error: {exc}\n")
        finally:
            self._update_action_states()

    def _edit_selected_avd(self) -> None:
        avd_name = self.selected_avd_var.get().strip()
        if not avd_name:
            messagebox.showerror("AVD requerido", "Selecciona un AVD para editar.")
            return
        self.open_edit_dialog(avd_name)

    def _delete_selected_avd(self) -> None:
        avd_name = self.selected_avd_var.get().strip()
        if not avd_name:
            messagebox.showerror("AVD requerido", "Selecciona un AVD para eliminar.")
            return
        self.confirm_delete(avd_name)

    def open_edit_dialog(self, avd_name: str) -> None:
        config_path, config = self.avd_service.get_editable_avd_config(avd_name)
        if not config_path:
            messagebox.showerror("Error", f"No se encontró config.ini para {avd_name}.")
            return

        dialog = tk.Toplevel(self)
        dialog.title(f"Editar {avd_name}")
        dialog.configure(bg="#101721")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("560x360")
        dialog.minsize(520, 330)
        dialog.columnconfigure(0, weight=1)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

        frame = ttk.Frame(dialog, style="Card.TFrame", padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text=f"Archivo: {config_path}", style="Hint.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ram_var = tk.StringVar(value=config.get("hw.ramSize", "2048"))
        heap_var = tk.StringVar(value=config.get("vm.heapSize", "256"))
        partition_var = tk.StringVar(value=config.get("disk.dataPartition.size", "2G"))
        frame_var = tk.StringVar(value=config.get("showDeviceFrame", "yes"))
        status_var = tk.StringVar(value="")

        ttk.Label(frame, text="RAM (MB)").grid(row=1, column=0, sticky="w")
        ttk.Entry(frame, textvariable=ram_var, style="Dark.TEntry").grid(row=1, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="VM Heap (MB)").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=heap_var, style="Dark.TEntry").grid(row=2, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="Data partition").grid(row=3, column=0, sticky="w")
        ttk.Entry(frame, textvariable=partition_var, style="Dark.TEntry").grid(row=3, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="Show device frame").grid(row=4, column=0, sticky="w")
        frame_combo = ttk.Combobox(frame, values=["yes", "no"], textvariable=frame_var, state="readonly")
        frame_combo.grid(row=4, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(frame, textvariable=status_var, style="Hint.TLabel").grid(row=5, column=0, columnspan=2, sticky="w")

        initial_values = {
            "hw.ramSize": ram_var.get().strip(),
            "vm.heapSize": heap_var.get().strip(),
            "disk.dataPartition.size": partition_var.get().strip().upper(),
            "showDeviceFrame": frame_var.get().strip().lower(),
        }

        def save_edit() -> None:
            ok, updates, message = self.avd_service.normalize_avd_config_inputs(
                ram_mb=ram_var.get().strip(),
                heap_mb=heap_var.get().strip(),
                data_partition=partition_var.get().strip(),
                show_device_frame=frame_var.get().strip() or "yes",
            )
            if not ok or updates is None:
                status_var.set(message)
                return

            if updates == initial_values:
                dialog.destroy()
                return

            updated, save_message = self.avd_service.update_avd_config(
                avd_name=avd_name,
                ram_mb=updates["hw.ramSize"],
                heap_mb=updates["vm.heapSize"],
                data_partition=updates["disk.dataPartition.size"],
                show_device_frame=updates["showDeviceFrame"],
            )
            if not updated:
                status_var.set(save_message)
                return

            dialog.destroy()
            self._invalidate_avd_cache()
            self.list_avds()
            self._append_log(f"[edit-avd] {avd_name}: {save_message}\n")
            self.show_feedback(f"Configuración guardada para {avd_name}.")

        action_row = ttk.Frame(frame, style="Card.TFrame")
        action_row.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(action_row, text="Cancelar", style="Neutral.TButton", command=dialog.destroy).pack(side="right")
        ttk.Button(action_row, text="Guardar", style="Primary.TButton", command=save_edit).pack(side="right", padx=(0, 8))

    def confirm_delete(self, avd_name: str) -> None:
        if avd_name in self.deleting_avd_names:
            return
        if not messagebox.askyesno("Eliminar AVD", f"¿Seguro que quieres eliminar el AVD '{avd_name}'?"):
            return

        pre_delete_names = set(self.avd_by_name.keys())
        self.deleting_avd_names.add(avd_name)
        self._update_action_states()
        self._populate_avd_tree(self.avd_items)
        self._append_log(f"[delete-avd:{avd_name}] Eliminando...\n")

        def worker() -> None:
            code, output = self.avd_service.delete_avd(avd_name, self.avdmanager_bin_var.get().strip())

            def finish() -> None:
                self.deleting_avd_names.discard(avd_name)
                self._invalidate_avd_cache()
                self.list_avds()
                if code != 0:
                    self._append_log(f"[delete-avd:{avd_name}] Falló eliminación.\n{output}\n")
                    self.show_feedback(f"No se pudo eliminar {avd_name}.", error=True)
                    messagebox.showerror("Error", f"No se pudo eliminar {avd_name}. Revisa el log.")
                    return
                current_names = set(self.avd_by_name.keys())
                unexpected_removed = sorted(name for name in (pre_delete_names - current_names) if name != avd_name)
                if unexpected_removed:
                    removed_text = ", ".join(unexpected_removed)
                    self._append_log(
                        f"[delete-avd:{avd_name}] Advertencia: también desaparecieron AVD(s): {removed_text}\n"
                    )
                    self.show_feedback(
                        f"Se eliminó {avd_name}, pero faltan además: {removed_text}. Revisa el estado de AVDs.",
                        error=True,
                    )
                    messagebox.showwarning(
                        "Revisión recomendada",
                        f"Se eliminó {avd_name}, pero también faltan: {removed_text}.",
                    )
                self._append_log(f"[delete-avd:{avd_name}] Eliminado correctamente.\n")
                self.show_feedback(f"{avd_name} eliminado.")

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def list_devices(self) -> None:
        avdmanager_bin = self.avdmanager_bin_var.get().strip()
        if not Path(avdmanager_bin).exists():
            messagebox.showerror("Ruta inválida", "No se encontró avdmanager.")
            return
        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        cache_key = self._devices_cache_key()
        loaded_at = self.devices_cache_time.get(cache_key, 0.0)
        if cache_key in self.devices_cache and (time.time() - loaded_at) <= self.CACHE_TTL_SECONDS:
            devices = self.devices_cache[cache_key]
            self.log_queue.put(f"[avdmanager-list-device] Cache: {len(devices)} devices.\n")
            return

        code, devices, _output = self.avd_service.list_available_devices(avdmanager_bin=avdmanager_bin)
        if code != 0:
            messagebox.showerror("Error", "No se pudieron listar los devices. Revisa el log.")
            return
        self.devices_cache[cache_key] = devices
        self.devices_cache_time[cache_key] = time.time()
        preferred = self.create_device_var.get().strip() or str(self.config.get("last_device_id", ""))
        if preferred and any(device.device_id == preferred for device in devices):
            self.create_device_var.set(preferred)
        elif devices:
            self.create_device_var.set(devices[0].device_id)
        self.log_queue.put(f"[avdmanager-list-device] {len(devices)} devices detectados.\n")
        self.save_config()

    def list_images(self) -> None:
        sdkmanager_bin = self.sdkmanager_bin_var.get().strip()
        if not Path(sdkmanager_bin).exists():
            messagebox.showerror("Ruta inválida", "No se encontró sdkmanager.")
            return
        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        cache_key = self._images_cache_key()
        loaded_at = self.images_cache_time.get(cache_key, 0.0)
        if cache_key in self.images_cache and (time.time() - loaded_at) <= self.CACHE_TTL_SECONDS:
            images = self.images_cache[cache_key]
            self.log_queue.put(f"[sdkmanager-list] Cache: {len(images)} imágenes.\n")
            return

        code, images, _output = self.avd_service.list_available_images(sdkmanager_bin=sdkmanager_bin)
        if code != 0:
            messagebox.showerror("Error", "No se pudieron listar las imágenes. Revisa el log.")
            return
        self.images_cache[cache_key] = images
        self.images_cache_time[cache_key] = time.time()
        preferred = self.create_package_var.get().strip() or str(self.config.get("last_image_package", ""))
        if preferred and preferred in images:
            self.create_package_var.set(preferred)
        elif images:
            self.create_package_var.set(images[0])
        self.log_queue.put(f"[sdkmanager-list] {len(images)} imágenes detectadas.\n")
        self.save_config()

    def _device_option_label(self, device: DeviceInfo) -> str:
        parts = [device.name, f"({device.device_id})"]
        if device.tag:
            parts.append(f"- {device.tag}")
        return " ".join(parts)

    def open_image_management_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Management Images")
        dialog.configure(bg="#101721")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("820x320")
        dialog.minsize(760, 300)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        frame = ttk.Frame(dialog, style="Card.TFrame", padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        image_var = tk.StringVar()
        status_var = tk.StringVar(value="")
        hint_var = tk.StringVar(value="Refresca para cargar catálogo de imágenes.")
        busy = {"value": False}
        auto_opened_log = {"value": False}
        image_catalog: dict[str, ImagePackageInfo] = {}

        ttk.Label(frame, text="System image").grid(row=0, column=0, sticky="w")
        images_combo = ttk.Combobox(frame, textvariable=image_var, state="readonly")
        images_combo.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(frame, textvariable=hint_var, style="Hint.TLabel").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, textvariable=status_var, style="Hint.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        action_row = ttk.Frame(frame, style="Card.TFrame")
        action_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        refresh_button = ttk.Button(action_row, text="Refrescar", style="Neutral.TButton")
        refresh_button.pack(side="left")
        install_button = ttk.Button(action_row, text="Instalar", style="Neutral.TButton")
        install_button.pack(side="left", padx=(8, 0))
        update_button = ttk.Button(action_row, text="Actualizar", style="Neutral.TButton")
        update_button.pack(side="left", padx=(8, 0))
        install_button.configure(state="disabled")
        update_button.configure(state="disabled")
        close_button = ttk.Button(action_row, text="Cerrar", style="Primary.TButton")
        close_button.pack(side="right")

        def selected_info() -> ImagePackageInfo | None:
            return image_catalog.get(image_var.get().strip())

        def set_controls_enabled(enabled: bool) -> None:
            state = "normal" if enabled else "disabled"
            images_combo.configure(state="readonly" if enabled else "disabled")
            refresh_button.configure(state=state)
            install_button.configure(state=state)
            update_button.configure(state=state)
            close_button.configure(state=state)

        def _has_license_issue(output: str) -> bool:
            lowered = output.lower()
            return "license" in lowered and ("not accepted" in lowered or "accept the sdk licenses" in lowered)

        def ensure_log_visible_for_image_ops() -> None:
            if not self.log_expanded:
                self._set_log_expanded(True, persist=False)
                auto_opened_log["value"] = True

        def handle_dialog_close(_event=None) -> None:
            if busy["value"]:
                status_var.set("Espera a que termine la operación antes de cerrar.")
                return
            if auto_opened_log["value"] and self.log_expanded:
                self._set_log_expanded(False, persist=False)
            dialog.destroy()

        def update_hint() -> None:
            info = selected_info()
            if not info:
                hint_var.set("Selecciona una imagen del catálogo.")
            elif info.installed and info.updatable:
                hint_var.set("Instalada, con actualización disponible.")
            elif info.installed:
                hint_var.set("Instalada, sin actualizaciones pendientes.")
            else:
                hint_var.set("No instalada.")

            if busy["value"]:
                install_button.configure(state="disabled")
                update_button.configure(state="disabled")
                return
            install_button.configure(state="normal" if info and not info.installed else "disabled")
            update_button.configure(state="normal" if info and info.installed and info.updatable else "disabled")

        def apply_catalog(items: list[ImagePackageInfo]) -> None:
            image_catalog.clear()
            for item in items:
                image_catalog[item.package] = item
            packages = [item.package for item in items]
            images_combo["values"] = packages
            preferred = self.create_package_var.get().strip()
            if preferred and preferred in image_catalog:
                image_var.set(preferred)
            elif packages:
                image_var.set(packages[0])
            else:
                image_var.set("")
            update_hint()

        def load_catalog() -> None:
            def worker() -> None:
                code, items, _output = self.avd_service.list_system_image_catalog(
                    sdkmanager_bin=self.sdkmanager_bin_var.get().strip()
                )
                if code != 0:
                    self.after(0, lambda: status_var.set("No se pudo leer catálogo de imágenes. Revisa el log."))
                    return
                installed_only = sorted(item.package for item in items if item.installed)
                cache_key = self._images_cache_key()
                self.images_cache[cache_key] = installed_only
                self.images_cache_time[cache_key] = time.time()
                self.after(0, lambda: apply_catalog(items))

            threading.Thread(target=worker, daemon=True).start()

        def run_image_op(kind: str) -> None:
            info = selected_info()
            if not info:
                status_var.set("Selecciona una imagen válida.")
                return
            if kind == "install" and info.installed:
                status_var.set("Esa imagen ya está instalada.")
                return
            if kind == "update" and (not info.installed or not info.updatable):
                status_var.set("No hay actualización disponible para esa imagen.")
                return

            accept = messagebox.askyesno(
                "Licencias",
                "¿Aceptar automáticamente contratos/licencias durante esta operación?",
            )
            ensure_log_visible_for_image_ops()
            busy["value"] = True
            set_controls_enabled(False)
            status_var.set("Instalando imagen..." if kind == "install" else "Actualizando imagen...")
            package = info.package
            self._append_log(f"[sdkmanager-{kind}] package={package}\n")
            self._append_log(f"[sdkmanager-{kind}] Inicio de operación para {package}\n")

            def worker() -> None:
                if kind == "install":
                    code, output = self.avd_service.install_system_image(
                        package=package,
                        sdkmanager_bin=self.sdkmanager_bin_var.get().strip(),
                        accept_licenses=accept,
                    )
                else:
                    code, output = self.avd_service.update_system_image(
                        package=package,
                        sdkmanager_bin=self.sdkmanager_bin_var.get().strip(),
                        accept_licenses=accept,
                    )

                def finish() -> None:
                    busy["value"] = False
                    set_controls_enabled(True)
                    if code == 0:
                        status_var.set("Operación completada.")
                        self.images_cache.clear()
                        self.images_cache_time.clear()
                        load_catalog()
                        self.show_feedback("Imágenes actualizadas.")
                        self._append_log(f"[sdkmanager-{kind}] Operación completada para {package}\n")
                    else:
                        if not accept and _has_license_issue(output):
                            status_var.set("Licencias pendientes. Usa 'Aceptar licencias' y reintenta.")
                            self._append_log(f"[sdkmanager-{kind}] Licencias pendientes para {package}\n")
                        else:
                            status_var.set("Falló la operación. Revisa el log.")
                            self._append_log(f"[sdkmanager-{kind}] Falló operación para {package}\n")
                        self.show_feedback("No se pudo completar la operación de imagen.", error=True)
                    update_hint()

                self.after(0, finish)

            threading.Thread(target=worker, daemon=True).start()

        images_combo.bind("<<ComboboxSelected>>", lambda _e: update_hint())
        refresh_button.configure(command=load_catalog)
        install_button.configure(command=lambda: run_image_op("install"))
        update_button.configure(command=lambda: run_image_op("update"))
        close_button.configure(command=handle_dialog_close)
        dialog.bind("<Escape>", handle_dialog_close)
        dialog.protocol("WM_DELETE_WINDOW", handle_dialog_close)
        load_catalog()

    def open_create_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Crear nuevo AVD")
        dialog.configure(bg="#101721")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("780x330")
        dialog.minsize(720, 300)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

        frame = ttk.Frame(dialog, style="Card.TFrame", padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        name_var = tk.StringVar()
        image_var = tk.StringVar(value=self.create_package_var.get().strip())
        device_var = tk.StringVar(value=self.create_device_var.get().strip())
        force_var = tk.BooleanVar(value=False)
        status_var = tk.StringVar(value="")
        duplicate_var = tk.StringVar(value="")
        create_busy = {"value": False}

        ttk.Label(frame, text="Nombre").grid(row=0, column=0, sticky="w")
        name_entry = ttk.Entry(frame, textvariable=name_var, style="Dark.TEntry")
        name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="System image").grid(row=1, column=0, sticky="w")
        images_combo = ttk.Combobox(frame, textvariable=image_var, state="readonly")
        images_combo.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(frame, text="Solo imágenes instaladas. Usa 'Management Images' para instalar o actualizar.", style="Hint.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w"
        )

        ttk.Label(frame, text="Device").grid(row=3, column=0, sticky="w", pady=(8, 0))
        devices_combo = ttk.Combobox(frame, textvariable=device_var, state="readonly")
        devices_combo.grid(row=3, column=1, sticky="ew", pady=(8, 8))

        ttk.Checkbutton(frame, text="Sobrescribir si existe", variable=force_var).grid(row=4, column=1, sticky="w", pady=(4, 8))
        ttk.Label(frame, textvariable=duplicate_var, style="Hint.TLabel").grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, textvariable=status_var, style="Hint.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

        action_row = ttk.Frame(frame, style="Card.TFrame")
        action_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        refresh_images_button = ttk.Button(action_row, text="Refrescar imágenes", style="Neutral.TButton")
        refresh_images_button.pack(side="left")
        manage_images_button = ttk.Button(action_row, text="Management Images", style="Neutral.TButton", command=self.open_image_management_dialog)
        manage_images_button.pack(side="left", padx=(8, 0))
        refresh_devices_button = ttk.Button(action_row, text="Refrescar devices", style="Neutral.TButton")
        refresh_devices_button.pack(side="left", padx=(8, 0))
        cancel_button = ttk.Button(action_row, text="Cancelar", style="Neutral.TButton", command=dialog.destroy)
        cancel_button.pack(side="right")
        create_button = ttk.Button(action_row, text="Crear", style="Primary.TButton")
        create_button.pack(side="right", padx=(0, 8))

        existing_avd_names = {item.name for item in self.avd_items}

        def set_controls_enabled(enabled: bool) -> None:
            state = "normal" if enabled else "disabled"
            name_entry.configure(state=state)
            images_combo.configure(state="readonly" if enabled else "disabled")
            devices_combo.configure(state="readonly" if enabled else "disabled")
            refresh_images_button.configure(state=state)
            manage_images_button.configure(state=state)
            refresh_devices_button.configure(state=state)
            cancel_button.configure(state=state)
            create_button.configure(state=state)

        def validate_create(*_args) -> None:
            name = name_var.get().strip()
            duplicate = name in existing_avd_names
            if duplicate and not force_var.get():
                duplicate_var.set("Ya existe un AVD con ese nombre. Activa 'Sobrescribir si existe' para continuar.")
            elif duplicate and force_var.get():
                duplicate_var.set("El nombre ya existe; se intentará sobrescribir.")
            else:
                duplicate_var.set("")
            installed_images = set(images_combo.cget("values") or [])
            allow = bool(
                name
                and image_var.get().strip()
                and image_var.get().strip() in installed_images
                and device_var.get().strip()
                and (not duplicate or force_var.get())
                and not create_busy["value"]
            )
            create_button.configure(state="normal" if allow else "disabled")

        def apply_images(images: list[str]) -> None:
            images_combo["values"] = images
            preferred = self.create_package_var.get().strip() or str(self.config.get("last_image_package", ""))
            if preferred and preferred in images:
                image_var.set(preferred)
            elif images:
                image_var.set(images[0])
            else:
                image_var.set("")
            validate_create()

        def apply_devices(devices: list[DeviceInfo]) -> None:
            values = [self._device_option_label(device) for device in devices]
            devices_combo["values"] = values
            mapping = {self._device_option_label(device): device.device_id for device in devices}
            reverse = {device.device_id: self._device_option_label(device) for device in devices}
            preferred = self.create_device_var.get().strip() or str(self.config.get("last_device_id", ""))
            if preferred and preferred in reverse:
                devices_combo.set(reverse[preferred])
            elif values:
                devices_combo.set(values[0])

            def sync_device_id(_event=None) -> None:
                selected_label = devices_combo.get().strip()
                if selected_label in mapping:
                    device_var.set(mapping[selected_label])
                    validate_create()

            devices_combo.bind("<<ComboboxSelected>>", sync_device_id)
            sync_device_id()

        def load_images(force_refresh: bool = False) -> None:
            def worker() -> None:
                cache_key = self._images_cache_key()
                loaded_at = self.images_cache_time.get(cache_key, 0.0)
                if not force_refresh and cache_key in self.images_cache and (time.time() - loaded_at) <= self.CACHE_TTL_SECONDS:
                    images = self.images_cache[cache_key]
                    self.after(0, lambda: apply_images(images))
                    return
                code, images, _output = self.avd_service.list_available_images(sdkmanager_bin=self.sdkmanager_bin_var.get().strip())
                if code != 0:
                    self.after(0, lambda: status_var.set("No se pudieron listar las imágenes. Revisa el log."))
                    return
                self.images_cache[cache_key] = images
                self.images_cache_time[cache_key] = time.time()
                self.after(0, lambda: apply_images(images))

            threading.Thread(target=worker, daemon=True).start()

        def load_devices(force_refresh: bool = False) -> None:
            def worker() -> None:
                cache_key = self._devices_cache_key()
                loaded_at = self.devices_cache_time.get(cache_key, 0.0)
                if not force_refresh and cache_key in self.devices_cache and (time.time() - loaded_at) <= self.CACHE_TTL_SECONDS:
                    devices = self.devices_cache[cache_key]
                    self.after(0, lambda: apply_devices(devices))
                    return
                code, devices, _output = self.avd_service.list_available_devices(avdmanager_bin=self.avdmanager_bin_var.get().strip())
                if code != 0:
                    self.after(0, lambda: status_var.set("No se pudieron listar los devices. Revisa el log."))
                    return
                self.devices_cache[cache_key] = devices
                self.devices_cache_time[cache_key] = time.time()
                self.after(0, lambda: apply_devices(devices))

            threading.Thread(target=worker, daemon=True).start()

        def submit() -> None:
            name = name_var.get().strip()
            package = image_var.get().strip()
            device = device_var.get().strip()
            if not name or not package or not device:
                status_var.set("Completa nombre, package y device.")
                return
            if name in existing_avd_names and not force_var.get():
                status_var.set("Ese AVD ya existe. Marca 'Sobrescribir si existe' o usa otro nombre.")
                return
            installed_images = set(images_combo.cget("values") or [])
            if package not in installed_images:
                status_var.set("La imagen seleccionada no está instalada. Usa Management Images.")
                return

            create_busy["value"] = True
            set_controls_enabled(False)
            status_var.set("Creando AVD...")
            self._append_log(f"[create-avd] package={package} device={device} name={name}\n")
            self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
            self._invalidate_avd_cache()
            self.create_package_var.set(package)
            self.create_device_var.set(device)
            self.save_config()

            def on_exit(code: int) -> None:
                if code == 0:
                    self.log_queue.put("[create-avd] AVD creado correctamente.\n")
                    self.after(0, self._invalidate_avd_cache)
                    self.after(0, self.list_avds)
                    self.after(0, lambda: self.show_feedback(f"AVD {name} creado."))
                    self.after(0, dialog.destroy)
                else:
                    self.log_queue.put("[create-avd] Falló la creación del AVD.\n")
                    self.after(0, lambda: status_var.set("Falló la creación del AVD. Revisa el log."))
                    self.after(0, lambda: self.show_feedback(f"Falló la creación de {name}.", error=True))
                    self.after(
                        0,
                        lambda: (
                            create_busy.__setitem__("value", False),
                            set_controls_enabled(True),
                            validate_create(),
                        ),
                    )

            proc = self.avd_service.create_avd(
                name=name,
                package=package,
                device=device,
                force=force_var.get(),
                avdmanager_bin=self.avdmanager_bin_var.get().strip(),
                on_exit=on_exit,
            )
            if proc is None:
                create_busy["value"] = False
                set_controls_enabled(True)
                status_var.set("No se pudo iniciar el proceso.")
                return

        create_button.configure(command=submit)
        refresh_images_button.configure(command=lambda: load_images(True))
        refresh_devices_button.configure(command=lambda: load_devices(True))
        name_var.trace_add("write", validate_create)
        force_var.trace_add("write", validate_create)
        image_var.trace_add("write", validate_create)
        device_var.trace_add("write", validate_create)
        validate_create()
        load_images(True)
        load_devices(False)
        name_entry.focus_set()

    def create_avd(self) -> None:
        avdmanager_bin = self.avdmanager_bin_var.get().strip()
        name = self.create_name_var.get().strip()
        package = self.create_package_var.get().strip()
        device = self.create_device_var.get().strip()

        if not Path(avdmanager_bin).exists():
            messagebox.showerror("Ruta inválida", "No se encontró avdmanager.")
            return
        if not name:
            messagebox.showerror("Dato faltante", "Debes indicar un nombre para el AVD.")
            return
        if not package:
            messagebox.showerror("Dato faltante", "Debes indicar el package de la imagen.")
            return
        if not device:
            messagebox.showerror("Dato faltante", "Debes indicar el device id.")
            return

        self._append_log("\n[create-avd] Nota: si la imagen no existe, primero instálala con sdkmanager.\n")
        self._append_log(f"[create-avd] package={package} device={device} name={name}\n")
        self.avd_service.set_sdk_root(self.android_sdk_root_var.get())
        self._invalidate_avd_cache()
        self.config["last_image_package"] = package
        self.config["last_device_id"] = device
        self.save_config()

        def on_exit(code: int) -> None:
            if code == 0:
                self.log_queue.put("[create-avd] AVD creado correctamente.\n")
                self.after(0, self._invalidate_avd_cache)
                self.after(0, self.list_avds)
            else:
                self.log_queue.put("[create-avd] Falló la creación del AVD.\n")

        proc = self.avd_service.create_avd(
            name=name,
            package=package,
            device=device,
            force=self.create_force_var.get(),
            avdmanager_bin=avdmanager_bin,
            on_exit=on_exit,
        )
        if proc is None:
            self._append_log("[create-avd] error: no se pudo iniciar el proceso.\n")


def main() -> None:
    app = EmulatorManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
