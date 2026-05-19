#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import platform
import queue
import subprocess
import time
from pathlib import Path

import flet as ft

from dialogs import open_create_dialog as show_create_dialog
from dialogs import open_edit_dialog as show_edit_dialog
from services.avd_service import AvdInfo, AvdService, DeviceInfo, EnvironmentStatus, BinaryStatus
from services.config_store import ConfigStore
from services.process_runner import ProcessRunner
from services.sdk_paths import AndroidSdkPaths
from views import build_dashboard_view


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / ".avd-manager.json"
CACHE_TTL_SECONDS = 600
AVD_LIST_CACHE_TTL_SECONDS = 5


def border_all(width: float, color: str) -> ft.Border:
    side = ft.BorderSide(width=width, color=color)
    return ft.Border(top=side, right=side, bottom=side, left=side)


class FletAvdApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.config_store = ConfigStore(CONFIG_PATH)
        self.config = self.config_store.load()
        self.log_queue: queue.Queue[str] = queue.Queue()
        initial_sdk_root = self.config.get("sdk_root", AndroidSdkPaths.default_sdk_root())
        self.runner = ProcessRunner(initial_sdk_root, self.log_queue)
        self.avd_service = AvdService(self.runner)

        self.avd_items: list[AvdInfo] = []
        self.emulator_process: subprocess.Popen | None = None
        self.log_expanded = bool(self.config.get("log_expanded", False))
        self.active_dialog: ft.AlertDialog | None = None
        self.refresh_target_name: str | None = None
        self.refresh_attempts_left = 0
        self.next_refresh_at = 0.0
        self.deleting_avd_names: set[str] = set()
        self.create_dialog_state: dict[str, object] | None = None
        self.env_status: EnvironmentStatus | None = None
        self.boot_status = "checking"
        self.last_validation_signature: tuple[str, str, str, str] | None = None
        self.last_validation_deep = False
        self.images_cache: dict[tuple[str, str], list[str]] = {}
        self.devices_cache: dict[tuple[str, str], list[DeviceInfo]] = {}
        self.images_cache_time: dict[tuple[str, str], float] = {}
        self.devices_cache_time: dict[tuple[str, str], float] = {}
        self.avd_list_cache: dict[tuple[str, str], list[AvdInfo]] = {}
        self.avd_list_cache_time: dict[tuple[str, str], float] = {}
        self.log_entries: list[dict[str, str]] = []

        self.sdk_root_field = ft.TextField(
            value=self.config.get("sdk_root", self.runner.sdk_root),
            border_radius=14,
            border_color="#304055",
            bgcolor="#151b24",
            color="#f5f7fb",
            text_size=14,
            expand=True,
        )
        self.emulator_path_field = ft.TextField(label="Ruta emulator", value=self.config.get("emulator_path", ""), border_radius=14, border_color="#304055", bgcolor="#151b24", color="#f5f7fb")
        self.avdmanager_path_field = ft.TextField(label="Ruta avdmanager", value=self.config.get("avdmanager_path", ""), border_radius=14, border_color="#304055", bgcolor="#151b24", color="#f5f7fb")
        self.sdkmanager_path_field = ft.TextField(label="Ruta sdkmanager", value=self.config.get("sdkmanager_path", ""), border_radius=14, border_color="#304055", bgcolor="#151b24", color="#f5f7fb")
        self.log_filter = ft.Dropdown(
            value="all",
            width=160,
            options=[
                ft.dropdown.Option("all", "Todos"),
                ft.dropdown.Option("create", "Create"),
                ft.dropdown.Option("delete", "Delete"),
                ft.dropdown.Option("launch", "Launch"),
                ft.dropdown.Option("system", "System"),
            ],
            on_select=self._on_log_filter_change,
            border_radius=12,
            border_color="#253141",
            bgcolor="#0e131a",
            color="#dbe8ff",
            text_size=12,
        )
        self.clear_log_button = ft.OutlinedButton(
            "Limpiar log",
            icon=ft.Icons.DELETE_SWEEP_ROUNDED,
            on_click=self.clear_log,
            style=ft.ButtonStyle(
                color="#dbe8ff",
                side=ft.BorderSide(1, "#344255"),
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
        )
        self.log_view = ft.TextField(
            value="",
            multiline=True,
            min_lines=8,
            max_lines=18,
            read_only=True,
            border_radius=14,
            border_color="#253141",
            bgcolor="#0e131a",
            color="#dbe8ff",
            text_style=ft.TextStyle(font_family="Courier New", size=12),
            expand=True,
        )
        self.log_body = ft.Container(content=self.log_view, visible=self.log_expanded, expand=True)
        self.log_header_icon = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED if self.log_expanded else ft.Icons.KEYBOARD_ARROW_UP_ROUNDED,
            color="#a8bbd9",
        )
        self.log_header_label = ft.Text(
            "Log expandido" if self.log_expanded else "Log minimizado",
            color="#dbe8ff",
            weight=ft.FontWeight.W_600,
        )
        self.cards_column = ft.Column(spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)
        self.banner_text = ft.Text("", color="#dbe8ff", size=13)
        self.body_container = ft.Container(expand=True)
        self.configs_button = ft.FilledButton(
            "Configs",
            icon=ft.Icons.SETTINGS_ROUNDED,
            on_click=self.open_configs_dialog,
            style=ft.ButtonStyle(
                bgcolor="#192230",
                color="#eff4fd",
                padding=18,
                shape=ft.RoundedRectangleBorder(radius=14),
            ),
        )
        self.create_avd_button = ft.FilledButton(
            "Crear nuevo AVD",
            icon=ft.Icons.ADD_ROUNDED,
            on_click=self.open_create_dialog,
            style=ft.ButtonStyle(
                bgcolor="#3478f6",
                color="#ffffff",
                padding=18,
                shape=ft.RoundedRectangleBorder(radius=14),
            ),
        )

        self.page.title = "Android Emulator Manager Flet"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#0b1016"
        self.page.padding = 20
        self.page.window_min_width = 1120
        self.page.window_min_height = 760
        self.page.on_keyboard_event = self._on_keyboard_event
        self.sdk_root_field.on_change = self._on_path_fields_changed
        self.emulator_path_field.on_change = self._on_path_fields_changed
        self.avdmanager_path_field.on_change = self._on_path_fields_changed
        self.sdkmanager_path_field.on_change = self._on_path_fields_changed
        self._load_persisted_caches()

        self.page.add(self._build_layout())
        self.page.run_task(self._log_pump)
        self.refresh_all()

    def _build_layout(self) -> ft.Control:
        return ft.Column(
            controls=[
                self._build_header(),
                ft.Container(height=14),
                self.body_container,
                ft.Container(height=14),
                self._build_log_panel(),
            ],
            expand=True,
            spacing=0,
        )

    def _build_header(self) -> ft.Control:
        title_block = ft.Column(
            controls=[
                ft.Text("Android Emulator Manager", size=28, weight=ft.FontWeight.BOLD, color="#f7f9fc"),
                ft.Text("UI moderna en Flet reutilizando la lógica de AVD existente.", size=13, color="#8ea2bf"),
            ],
            spacing=4,
            expand=True,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            title_block,
                            self.configs_button,
                            self.create_avd_button,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=16),
                    ft.Row(
                        controls=[
                            self.sdk_root_field,
                            ft.IconButton(
                                icon=ft.Icons.REFRESH_ROUNDED,
                                tooltip="Recalcular rutas y refrescar AVDs",
                                on_click=lambda _e: self.refresh_all(deep_validate=True),
                                style=ft.ButtonStyle(bgcolor="#192230", color="#eff4fd"),
                            ),
                        ],
                    ),
                ],
                spacing=0,
            ),
            padding=22,
            bgcolor="#101721",
            border_radius=24,
            border=border_all(1, "#223041"),
        )

    def _build_log_panel(self) -> ft.Control:
        self.log_toolbar = ft.Container(
            content=ft.Row(
                controls=[
                    self.log_filter,
                    self.clear_log_button,
                ],
                alignment=ft.MainAxisAlignment.END,
            ),
            visible=self.log_expanded,
            padding=ft.Padding(left=8, top=4, right=8, bottom=8),
        )
        self.log_panel = ft.Container(
            content=ft.Column(
                controls=[
                    ft.TextButton(
                        content=ft.Row(
                            controls=[
                                self.log_header_icon,
                                self.log_header_label,
                                ft.Text("Haz click para expandir u ocultar", color="#7c91b1", size=12),
                            ],
                            spacing=12,
                        ),
                        on_click=self.toggle_log,
                        style=ft.ButtonStyle(
                            padding=18,
                            shape=ft.RoundedRectangleBorder(radius=16),
                            color="#dbe8ff",
                        ),
                    ),
                    self.log_toolbar,
                    self.log_body,
                ],
                spacing=0,
                expand=True,
            ),
            height=360 if self.log_expanded else 68,
            animate=ft.Animation(240, ft.AnimationCurve.EASE_OUT),
            bgcolor="#101721",
            border_radius=24,
            border=border_all(1, "#223041"),
            padding=10,
        )
        return self.log_panel

    def set_sdk_root(self) -> None:
        self.runner.set_sdk_root(self.sdk_root_field.value.strip())

    def _on_path_fields_changed(self, _event=None) -> None:
        self.last_validation_signature = None
        self.invalidate_avd_cache()

    def _images_cache_key(self) -> tuple[str, str]:
        return (self.sdk_root_field.value.strip(), self.sdkmanager_path_field.value.strip())

    def _devices_cache_key(self) -> tuple[str, str]:
        return (self.sdk_root_field.value.strip(), self.avdmanager_path_field.value.strip())

    def _avd_list_cache_key(self) -> tuple[str, str]:
        return (self.sdk_root_field.value.strip(), self.emulator_path_field.value.strip())

    @staticmethod
    def _format_loaded_at(timestamp: float | None) -> str:
        if not timestamp:
            return "Última carga: --"
        return f"Última carga: {time.strftime('%H:%M:%S', time.localtime(timestamp))}"

    def _load_persisted_caches(self) -> None:
        now = time.time()

        raw_images_cache = self.config.get("images_cache", {})
        if isinstance(raw_images_cache, dict):
            for cache_key, payload in raw_images_cache.items():
                if not isinstance(payload, dict):
                    continue
                loaded_at = float(payload.get("loaded_at", 0) or 0)
                items = payload.get("items", [])
                if now - loaded_at > CACHE_TTL_SECONDS or not isinstance(items, list):
                    continue
                sdk_root, sdkmanager_path = cache_key.split("|", 1) if "|" in cache_key else (cache_key, "")
                self.images_cache[(sdk_root, sdkmanager_path)] = [str(item) for item in items]
                self.images_cache_time[(sdk_root, sdkmanager_path)] = loaded_at

        raw_devices_cache = self.config.get("devices_cache", {})
        if isinstance(raw_devices_cache, dict):
            for cache_key, payload in raw_devices_cache.items():
                if not isinstance(payload, dict):
                    continue
                loaded_at = float(payload.get("loaded_at", 0) or 0)
                items = payload.get("items", [])
                if now - loaded_at > CACHE_TTL_SECONDS or not isinstance(items, list):
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

    def invalidate_avd_cache(self) -> None:
        self.avd_list_cache.clear()
        self.avd_list_cache_time.clear()

    def refresh_all(self, deep_validate: bool = False) -> None:
        self.set_sdk_root()
        self.validate_environment(deep=deep_validate)
        self.save_config()
        if self.env_status and not self.env_status.needs_setup and self.env_status.can_list_avds:
            self.refresh_avds(force_refresh=deep_validate)
        self.update_header_actions()
        self.render_body()
        self.page.update()

    def validate_environment(self, deep: bool = False) -> None:
        signature = (
            self.sdk_root_field.value.strip(),
            self.emulator_path_field.value.strip(),
            self.avdmanager_path_field.value.strip(),
            self.sdkmanager_path_field.value.strip(),
        )
        if self.env_status is not None and signature == self.last_validation_signature and (self.last_validation_deep or not deep):
            return

        self.boot_status = "checking"
        self.page.update()

        sdk_root = self.sdk_root_field.value.strip()
        emulator_path = self.emulator_path_field.value.strip() or None
        avdmanager_path = self.avdmanager_path_field.value.strip() or None
        sdkmanager_path = self.sdkmanager_path_field.value.strip() or None

        self.env_status = self.avd_service.validate_environment(
            sdk_root=sdk_root,
            emulator_path=emulator_path,
            avdmanager_path=avdmanager_path,
            sdkmanager_path=sdkmanager_path,
            deep=deep,
        )
        self.last_validation_signature = signature
        self.last_validation_deep = deep

        self.emulator_path_field.value = self.env_status.emulator.path
        self.avdmanager_path_field.value = self.env_status.avdmanager.path
        self.sdkmanager_path_field.value = self.env_status.sdkmanager.path

        if self.env_status.is_ready:
            self.boot_status = "ready"
        elif self.env_status.needs_setup:
            self.boot_status = "needs_setup"
        else:
            self.boot_status = "partial_ready"
        self.save_config()

    def update_header_actions(self) -> None:
        self.configs_button.disabled = self.boot_status == "checking"
        self.create_avd_button.disabled = not bool(self.env_status and self.env_status.can_create and not self.env_status.needs_setup)

    def refresh_avds(self, force_refresh: bool = False) -> None:
        if not self.env_status or not self.env_status.can_list_avds:
            self.avd_items = []
            return
        self.set_sdk_root()
        cache_key = self._avd_list_cache_key()
        cache_time = self.avd_list_cache_time.get(cache_key, 0.0)
        if not force_refresh and cache_key in self.avd_list_cache and (time.time() - cache_time) <= AVD_LIST_CACHE_TTL_SECONDS:
            self.avd_items = self.avd_list_cache[cache_key]
            self.render_body()
            return

        code, avd_items, _output = self.avd_service.list_avd_info(emulator_bin=self.emulator_path_field.value.strip())
        if code != 0:
            self.show_snackbar("No se pudieron listar los AVDs.", error=True)
            return

        self.avd_items = avd_items
        self.avd_list_cache[cache_key] = avd_items
        self.avd_list_cache_time[cache_key] = time.time()
        self.render_body()

    def render_body(self) -> None:
        if self.boot_status == "checking":
            self.body_container.content = self.build_boot_state()
            return

        if self.env_status and self.env_status.needs_setup:
            self.body_container.content = self.build_setup_state()
            return

        self.body_container.content = build_dashboard_view(self, border_all)

    def build_boot_state(self) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.ProgressRing(width=28, height=28, stroke_width=3, color="#4f8cff"),
                    ft.Text("Detectando entorno Android SDK...", size=18, weight=ft.FontWeight.BOLD, color="#eef4ff"),
                ],
                spacing=16,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
            bgcolor="#101721",
            border_radius=24,
            border=border_all(1, "#223041"),
        )

    def build_setup_state(self) -> ft.Control:
        checks = []
        if self.env_status:
            checks = [
                self.build_check_row(self.env_status.emulator),
                self.build_check_row(self.env_status.avdmanager),
                self.build_check_row(self.env_status.sdkmanager),
            ]

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Configura tu Android SDK", size=24, weight=ft.FontWeight.BOLD, color="#eef4ff"),
                    ft.Text("La app no mostrará AVDs ni permitirá crear nuevos hasta validar el entorno.", color="#8ea2bf"),
                    self.sdk_root_field,
                    self.emulator_path_field,
                    self.avdmanager_path_field,
                    self.sdkmanager_path_field,
                    ft.Row(
                        controls=[
                            ft.FilledButton("Autodetectar", on_click=lambda _e: self.autodetect_paths(), icon=ft.Icons.AUTO_FIX_HIGH_ROUNDED),
                            ft.OutlinedButton("Validar", on_click=lambda _e: self.refresh_all(deep_validate=True), icon=ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED),
                            ft.OutlinedButton("Restablecer configuración", on_click=lambda _e: self.reset_configuration(), icon=ft.Icons.RESTART_ALT_ROUNDED),
                        ],
                        spacing=12,
                    ),
                    ft.Container(
                        content=ft.Column(controls=checks, spacing=10),
                        bgcolor="#151d28",
                        border_radius=18,
                        padding=16,
                    ),
                ],
                spacing=18,
            ),
            expand=True,
            bgcolor="#101721",
            border_radius=24,
            border=border_all(1, "#223041"),
            padding=24,
        )

    def build_check_row(self, status: BinaryStatus) -> ft.Control:
        color = "#41d391" if status.usable else "#f0a54a" if status.exists else "#d86464"
        label = "OK" if status.usable else status.detail
        return ft.Row(
            controls=[
                ft.Icon(ft.Icons.CIRCLE, size=12, color=color),
                ft.Text(f"{status.label}: {label}", color="#eef4ff", width=220),
                ft.Text(status.path, color="#8ea2bf", selectable=True, expand=True),
            ],
            spacing=12,
        )

    def autodetect_paths(self) -> None:
        self.sdk_root_field.value = AndroidSdkPaths.default_sdk_root()
        self.emulator_path_field.value = ""
        self.avdmanager_path_field.value = ""
        self.sdkmanager_path_field.value = ""
        self.last_validation_signature = None
        self.images_cache.clear()
        self.devices_cache.clear()
        self.images_cache_time.clear()
        self.devices_cache_time.clear()
        self.invalidate_avd_cache()
        self.refresh_all()

    def reset_configuration(self) -> None:
        self.config = {}
        self.config_store.save({})
        self.sdk_root_field.value = AndroidSdkPaths.default_sdk_root()
        self.emulator_path_field.value = ""
        self.avdmanager_path_field.value = ""
        self.sdkmanager_path_field.value = ""
        self.last_validation_signature = None
        self.last_validation_deep = False
        self.images_cache.clear()
        self.devices_cache.clear()
        self.images_cache_time.clear()
        self.devices_cache_time.clear()
        self.invalidate_avd_cache()
        self.refresh_all()

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

        data = {
            "sdk_root": self.sdk_root_field.value.strip(),
            "emulator_path": self.emulator_path_field.value.strip(),
            "avdmanager_path": self.avdmanager_path_field.value.strip(),
            "sdkmanager_path": self.sdkmanager_path_field.value.strip(),
            "last_image_package": self.config.get("last_image_package", ""),
            "last_device_id": self.config.get("last_device_id", ""),
            "images_cache": serialized_images_cache,
            "devices_cache": serialized_devices_cache,
            "log_expanded": self.log_expanded,
        }
        self.config = data
        self.config_store.save(data)

    def show_dialog(self, dialog: ft.AlertDialog) -> None:
        self.active_dialog = dialog
        self.page.show_dialog(dialog)

    def close_dialog(self, dialog: ft.AlertDialog) -> None:
        dialog.open = False
        self.page.pop_dialog()
        if self.active_dialog is dialog:
            self.active_dialog = None
        self.page.update()

    def _on_keyboard_event(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape" and self.active_dialog and self.active_dialog.open:
            self.close_dialog(self.active_dialog)

    def open_configs_dialog(self, _event) -> None:
        self.set_sdk_root()
        derived = {
            "emulator": self.emulator_path_field.value.strip(),
            "avdmanager": self.avdmanager_path_field.value.strip(),
            "sdkmanager": self.sdkmanager_path_field.value.strip(),
        }
        dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#111823",
            title=ft.Text("Configuración actual", color="#eff4fd", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                width=720,
                content=ft.Column(
                    controls=[
                        self.config_line("Sistema operativo", platform.system()),
                        self.config_line("Android SDK Root", self.sdk_root_field.value.strip()),
                        self.config_line("emulator", derived["emulator"]),
                        self.config_line("avdmanager", derived["avdmanager"]),
                        self.config_line("sdkmanager", derived["sdkmanager"]),
                    ],
                    spacing=12,
                    tight=True,
                ),
            ),
            actions=[ft.TextButton("Cerrar", on_click=lambda _e: self.close_dialog(dialog))],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.show_dialog(dialog)

    def config_line(self, label: str, value: str) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(label, color="#7c91b1", size=12),
                    ft.Text(value, color="#eff4fd", selectable=True),
                ],
                spacing=4,
            ),
            bgcolor="#151d28",
            border_radius=16,
            padding=14,
        )

    def open_create_dialog(self, _event) -> None:
        show_create_dialog(self, _event)

    def _device_option_label(self, device: DeviceInfo) -> str:
        parts = [device.name, f"({device.device_id})"]
        if device.tag:
            parts.append(f"- {device.tag}")
        return " ".join(parts)

    def _apply_selected_device(self, _event: ft.ControlEvent) -> None:
        if _event.control.value:
            self.config["last_device_id"] = _event.control.value
            self.save_config()
        self.page.update()

    def open_edit_dialog(self, avd_name: str) -> None:
        show_edit_dialog(self, avd_name)

    def confirm_delete(self, avd_name: str) -> None:
        async def remove_async(avd_to_delete: str) -> None:
            code, _output = await asyncio.to_thread(self.avd_service.delete_avd, avd_to_delete, self.avdmanager_path_field.value.strip())
            self.deleting_avd_names.discard(avd_to_delete)
            self.invalidate_avd_cache()
            if code != 0:
                self.refresh_avds(force_refresh=True)
                self.show_snackbar(f"No se pudo eliminar {avd_to_delete}.", error=True)
                return
            self.refresh_avds(force_refresh=True)
            self.show_snackbar(f"{avd_to_delete} eliminado.")

        def remove(_e) -> None:
            self.close_dialog(dialog)
            self.set_sdk_root()
            self.deleting_avd_names.add(avd_name)
            self.invalidate_avd_cache()
            self.refresh_avds(force_refresh=True)
            self.show_snackbar(f"Eliminando {avd_name}...")

            async def remove_task() -> None:
                await remove_async(avd_name)

            self.page.run_task(remove_task)

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#111823",
            title=ft.Text("Eliminar AVD", color="#eff4fd", weight=ft.FontWeight.BOLD),
            content=ft.Text(
                f"¿Seguro que quieres eliminar el AVD '{avd_name}'?\nEsta acción elimina su definición local.",
                color="#dbe8ff",
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _e: self.close_dialog(dialog)),
                ft.FilledButton(
                    "Eliminar",
                    on_click=remove,
                    style=ft.ButtonStyle(bgcolor="#cf4d4d", color="#ffffff"),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.show_dialog(dialog)

    def launch_avd(self, avd_name: str) -> None:
        if self.emulator_process and self.emulator_process.poll() is None:
            self.show_snackbar("Ya hay un emulador iniciado desde esta app.", error=True)
            return

        self.set_sdk_root()
        proc = self.avd_service.launch_emulator(avd_name, emulator_bin=self.emulator_path_field.value.strip())
        if proc is None:
            self.show_snackbar(f"No se pudo iniciar {avd_name}.", error=True)
            return

        self.emulator_process = proc
        self.show_snackbar(f"Lanzando {avd_name}...")

    def toggle_log(self, _event) -> None:
        self.log_expanded = not self.log_expanded
        self.log_body.visible = self.log_expanded
        self.log_body.expand = self.log_expanded
        self.log_header_label.value = "Log expandido" if self.log_expanded else "Log minimizado"
        self.log_header_icon.name = (
            ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED if self.log_expanded else ft.Icons.KEYBOARD_ARROW_UP_ROUNDED
        )
        self.log_panel.height = 360 if self.log_expanded else 68
        self.log_toolbar.visible = self.log_expanded
        self.save_config()
        self.page.update()

    def _detect_log_category(self, message: str) -> str:
        if "[create-avd]" in message:
            return "create"
        if "[delete-avd:" in message:
            return "delete"
        if "[launch:" in message:
            return "launch"
        return "system"

    def _apply_log_view(self) -> None:
        filter_value = self.log_filter.value or "all"
        visible_entries = self.log_entries
        if filter_value != "all":
            visible_entries = [entry for entry in self.log_entries if entry["category"] == filter_value]
        self.log_view.value = "".join(entry["text"] for entry in visible_entries[-500:])

    def clear_log(self, _event=None) -> None:
        self.log_entries.clear()
        self._apply_log_view()
        self.page.update()

    def _on_log_filter_change(self, _event=None) -> None:
        self._apply_log_view()
        self.page.update()

    def show_snackbar(self, message: str, error: bool = False) -> None:
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor="#bc4747" if error else "#1f7a52",
        )
        self.page.snack_bar.open = True
        self.page.update()

    async def _log_pump(self) -> None:
        while True:
            changed = False
            while True:
                try:
                    msg = self.log_queue.get_nowait()
                    if msg.startswith("__REFRESH_AVDS__:"):
                        self.refresh_target_name = msg.split(":", 1)[1].strip()
                        self.refresh_attempts_left = 8
                        self.next_refresh_at = 0.0
                        self.invalidate_avd_cache()
                        continue
                    if msg.startswith("__CREATE_RESULT__:"):
                        _prefix, avd_name, code_raw = msg.strip().split(":", 2)
                        code = int(code_raw)
                        if self.create_dialog_state:
                            setter = self.create_dialog_state.get("set_create_in_progress")
                            if callable(setter):
                                setter(False, "" if code == 0 else f"Falló la creación de {avd_name}. Revisa el log.")
                            dialog = self.create_dialog_state.get("dialog")
                            if code == 0 and isinstance(dialog, ft.AlertDialog):
                                self.close_dialog(dialog)
                                self.create_dialog_state = None
                                self.show_snackbar(f"Creación finalizada para {avd_name}.")
                            elif code != 0:
                                self.show_snackbar(f"Falló la creación de {avd_name}. Revisa el log.", error=True)
                        continue
                    timestamp = time.strftime("%H:%M:%S", time.localtime())
                    self.log_entries.append(
                        {
                            "category": self._detect_log_category(msg),
                            "text": f"[{timestamp}] {msg}",
                        }
                    )
                    if len(self.log_entries) > 1500:
                        self.log_entries = self.log_entries[-1500:]
                    changed = True
                except queue.Empty:
                    break

            if changed:
                self._apply_log_view()
                self.page.update()

            if self.refresh_target_name and self.refresh_attempts_left > 0 and time.monotonic() >= self.next_refresh_at:
                self.refresh_avds(force_refresh=True)
                avd_names = {item.name for item in self.avd_items}
                if self.refresh_target_name in avd_names:
                    self.show_snackbar(f"{self.refresh_target_name} ya aparece en la lista.")
                    self.refresh_target_name = None
                    self.refresh_attempts_left = 0
                else:
                    self.refresh_attempts_left -= 1
                    self.next_refresh_at = time.monotonic() + 1.0

            await asyncio.sleep(0.1 if changed or self.refresh_target_name else 0.5)


def main(page: ft.Page) -> None:
    FletAvdApp(page)


if __name__ == "__main__":
    ft.run(main, assets_dir=str(BASE_DIR))
