#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import platform
import queue
import subprocess
import time
from pathlib import Path

import flet as ft

from services.avd_service import AvdInfo, AvdService, DeviceInfo
from services.process_runner import ProcessRunner
from services.sdk_paths import AndroidSdkPaths


BASE_DIR = Path(__file__).resolve().parent


def border_all(width: float, color: str) -> ft.Border:
    side = ft.BorderSide(width=width, color=color)
    return ft.Border(top=side, right=side, bottom=side, left=side)


class FletAvdApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.runner = ProcessRunner(AndroidSdkPaths.default_sdk_root(), self.log_queue)
        self.avd_service = AvdService(self.runner)

        self.avd_items: list[AvdInfo] = []
        self.emulator_process: subprocess.Popen | None = None
        self.log_lines: list[str] = []
        self.log_expanded = False
        self.active_dialog: ft.AlertDialog | None = None
        self.refresh_target_name: str | None = None
        self.refresh_attempts_left = 0
        self.next_refresh_at = 0.0
        self.deleting_avd_names: set[str] = set()
        self.create_dialog_state: dict[str, object] | None = None

        self.sdk_root_field = ft.TextField(
            value=self.runner.sdk_root,
            border_radius=14,
            border_color="#304055",
            bgcolor="#151b24",
            color="#f5f7fb",
            text_size=14,
            expand=True,
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
        self.log_body = ft.Container(content=self.log_view, visible=False, expand=True)
        self.log_header_icon = ft.Icon(ft.Icons.KEYBOARD_ARROW_UP_ROUNDED, color="#a8bbd9")
        self.log_header_label = ft.Text("Log minimizado", color="#dbe8ff", weight=ft.FontWeight.W_600)
        self.cards_column = ft.Column(spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)

        self.page.title = "Android Emulator Manager Flet"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#0b1016"
        self.page.padding = 20
        self.page.window_min_width = 1120
        self.page.window_min_height = 760
        self.page.on_keyboard_event = self._on_keyboard_event

        self.page.add(self._build_layout())
        self.page.run_task(self._log_pump)
        self.refresh_all()

    def _build_layout(self) -> ft.Control:
        return ft.Column(
            controls=[
                self._build_header(),
                ft.Container(height=14),
                ft.Container(
                    content=self.cards_column,
                    expand=True,
                    border_radius=24,
                    bgcolor="#101721",
                    border=border_all(1, "#223041"),
                    padding=18,
                ),
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
                            ft.FilledButton(
                                "Configs",
                                icon=ft.Icons.SETTINGS_ROUNDED,
                                on_click=self.open_configs_dialog,
                                style=ft.ButtonStyle(
                                    bgcolor="#192230",
                                    color="#eff4fd",
                                    padding=18,
                                    shape=ft.RoundedRectangleBorder(radius=14),
                                ),
                            ),
                            ft.FilledButton(
                                "Crear nuevo AVD",
                                icon=ft.Icons.ADD_ROUNDED,
                                on_click=self.open_create_dialog,
                                style=ft.ButtonStyle(
                                    bgcolor="#3478f6",
                                    color="#ffffff",
                                    padding=18,
                                    shape=ft.RoundedRectangleBorder(radius=14),
                                ),
                            ),
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
                                on_click=lambda _e: self.refresh_all(),
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
                    self.log_body,
                ],
                spacing=0,
                expand=True,
            ),
            height=68,
            animate=ft.Animation(240, ft.AnimationCurve.EASE_OUT),
            bgcolor="#101721",
            border_radius=24,
            border=border_all(1, "#223041"),
            padding=10,
        )
        return self.log_panel

    def set_sdk_root(self) -> None:
        self.runner.set_sdk_root(self.sdk_root_field.value.strip())

    def refresh_all(self) -> None:
        self.set_sdk_root()
        self.refresh_avds()
        self.page.update()

    def refresh_avds(self) -> None:
        self.set_sdk_root()
        code, avd_items, _output = self.avd_service.list_avd_info()
        if code != 0:
            self.show_snackbar("No se pudieron listar los AVDs.", error=True)
            return

        self.avd_items = avd_items
        self.cards_column.controls = [self.build_avd_card(item) for item in avd_items] or [self.build_empty_state()]
        self.page.update()

    def build_empty_state(self) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.DEVICES_OTHER_OUTLINED, size=40, color="#6b809f"),
                    ft.Text("No se encontraron AVDs", size=20, weight=ft.FontWeight.BOLD, color="#eef4ff"),
                    ft.Text("Usa el botón Crear nuevo AVD o revisa las rutas en Configs.", color="#8ea2bf"),
                ],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            alignment=ft.Alignment(0, 0),
            height=320,
        )

    def build_avd_card(self, item: AvdInfo) -> ft.Control:
        is_deleting = item.name in self.deleting_avd_names
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Image(src="mobile.png", width=54, height=54, fit="contain"),
                        width=76,
                        height=76,
                        alignment=ft.Alignment(0, 0),
                        border_radius=20,
                        bgcolor="#151d28",
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(item.name, size=18, weight=ft.FontWeight.BOLD, color="#f5f8fe"),
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.CIRCLE, size=12, color="#41d391"),
                                    ft.Text(item.status, color="#8fa4c2", size=13),
                                ],
                                spacing=8,
                            ),
                        ],
                        spacing=8,
                        expand=True,
                    ),
                    ft.Row(
                        controls=[
                            ft.FilledButton(
                                "Lanzar",
                                icon=ft.Icons.PLAY_ARROW_ROUNDED,
                                on_click=lambda _e, avd=item.name: self.launch_avd(avd),
                                disabled=is_deleting,
                                style=ft.ButtonStyle(
                                    bgcolor="#2bb673",
                                    color="#ffffff",
                                    padding=18,
                                    shape=ft.RoundedRectangleBorder(radius=14),
                                ),
                            ),
                            ft.OutlinedButton(
                                "Editar",
                                icon=ft.Icons.TUNE_ROUNDED,
                                on_click=lambda _e, avd=item.name: self.open_edit_dialog(avd),
                                disabled=is_deleting,
                                style=ft.ButtonStyle(
                                    color="#e7edf8",
                                    side=ft.BorderSide(1, "#39485d"),
                                    padding=18,
                                    shape=ft.RoundedRectangleBorder(radius=14),
                                ),
                            ),
                            (
                                ft.FilledButton(
                                    "Eliminar",
                                    icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                                    on_click=lambda _e, avd=item.name: self.confirm_delete(avd),
                                    style=ft.ButtonStyle(
                                        bgcolor="#cf4d4d",
                                        color="#ffffff",
                                        padding=18,
                                        shape=ft.RoundedRectangleBorder(radius=14),
                                    ),
                                )
                                if not is_deleting
                                else ft.Container(
                                    content=ft.Row(
                                        controls=[
                                            ft.ProgressRing(width=16, height=16, stroke_width=2, color="#ffffff"),
                                            ft.Text("Eliminando...", color="#ffffff", size=13, weight=ft.FontWeight.W_600),
                                        ],
                                        spacing=10,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                    bgcolor="#7a3737",
                                    border_radius=14,
                                    padding=ft.Padding(left=16, top=12, right=16, bottom=12),
                                )
                            ),
                        ],
                        spacing=10,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#151d28",
            border_radius=22,
            border=border_all(1, "#263448"),
            padding=18,
        )

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
        derived = self.avd_service.derived_paths()
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
        name_field = ft.TextField(label="Nombre", autofocus=True)
        force_checkbox = ft.Checkbox(label="Sobrescribir si existe", value=False)
        create_button = ft.FilledButton("Crear", disabled=True)
        images_dropdown = ft.Dropdown(
            label="Imágenes disponibles",
            options=[],
            hint_text="Cargando imágenes disponibles...",
            disabled=True,
        )
        device_dropdown = ft.Dropdown(
            label="Device disponible",
            options=[],
            hint_text="Cargando devices disponibles",
            on_select=self._apply_selected_device,
            disabled=True,
        )
        loading_text = ft.Text("", color="#dbe8ff", size=13)
        loading_row = ft.Container(
            content=ft.Row(
                controls=[
                    ft.ProgressRing(width=18, height=18, stroke_width=2, color="#4f8cff"),
                    loading_text,
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=False,
            bgcolor="#151d28",
            border_radius=14,
            padding=12,
        )
        status_text = ft.Text("", color="#ef9090")
        images_total_text = ft.Text("Total imágenes: --", color="#8ea2bf", size=12)
        devices_total_text = ft.Text("Total devices: --", color="#8ea2bf", size=12)
        selected_package_text = ft.Text(
            f"Package seleccionado: {self.avd_service.default_image_package()}",
            color="#8ea2bf",
            size=12,
        )
        create_progress = ft.Container(
            content=ft.Row(
                controls=[
                    ft.ProgressRing(width=18, height=18, stroke_width=2, color="#4f8cff"),
                    ft.Text("Creando AVD...", color="#dbe8ff", size=13, weight=ft.FontWeight.W_600),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=False,
            bgcolor="#151d28",
            border_radius=14,
            padding=12,
        )
        loading_counter = {"count": 0}
        creating_state = {"active": False}

        def refresh_create_enabled(_event=None) -> None:
            can_create = (
                bool(name_field.value.strip())
                and bool((images_dropdown.value or "").strip())
                and bool((device_dropdown.value or "").strip())
                and not creating_state["active"]
            )
            create_button.disabled = not can_create
            self.page.update()

        name_field.on_change = refresh_create_enabled

        def apply_selected_image(_event: ft.ControlEvent) -> None:
            selected = images_dropdown.value
            if selected:
                selected_package_text.value = f"Package seleccionado: {selected}"
                self.page.update()

        images_dropdown.on_select = apply_selected_image

        def set_create_in_progress(in_progress: bool, message: str = "") -> None:
            creating_state["active"] = in_progress
            name_field.disabled = in_progress
            images_dropdown.disabled = in_progress or not bool(images_dropdown.options)
            device_dropdown.disabled = in_progress or not bool(device_dropdown.options)
            force_checkbox.disabled = in_progress
            create_button.text = "Creando..." if in_progress else "Crear"
            create_progress.visible = in_progress
            status_text.value = message
            refresh_create_enabled()
            self.page.update()

        def set_loading(message: str, visible: bool) -> None:
            if visible:
                loading_counter["count"] += 1
                loading_text.value = message
                loading_row.visible = True
            else:
                loading_counter["count"] = max(0, loading_counter["count"] - 1)
                if loading_counter["count"] == 0:
                    loading_text.value = ""
                    loading_row.visible = False
            self.page.update()

        def apply_images_result(code: int, images: list[str]) -> None:
            set_loading("", False)
            if code != 0:
                status_text.value = "No se pudieron listar las imágenes. Revisa el log."
                self.page.update()
                return
            if not images:
                status_text.value = "No se encontraron system images disponibles."
                self.page.update()
                return

            images_dropdown.options = [ft.dropdown.Option(image) for image in images]
            images_dropdown.value = self.avd_service.default_image_package() if self.avd_service.default_image_package() in images else images[0]
            images_dropdown.disabled = False
            images_dropdown.hint_text = "Selecciona una imagen"
            images_total_text.value = f"Total imágenes: {len(images)}"
            selected_package_text.value = f"Package seleccionado: {images_dropdown.value}"
            status_text.value = ""
            refresh_create_enabled()
            self.page.update()

        def load_images() -> tuple[int, list[str]]:
            set_loading("Consultando imágenes disponibles...", True)
            self.set_sdk_root()
            code, images, _output = self.avd_service.list_available_images()
            return code, images

        def apply_devices_result(code: int, devices: list[DeviceInfo]) -> None:
            set_loading("", False)
            if code != 0:
                status_text.value = "No se pudieron listar los devices. Revisa el log."
                self.page.update()
                return
            if not devices:
                status_text.value = "No se encontraron devices disponibles."
                self.page.update()
                return

            device_dropdown.options = [ft.dropdown.Option(device.device_id, self._device_option_label(device)) for device in devices]
            default_device = self.avd_service.default_device_id()
            selected_device = default_device if any(device.device_id == default_device for device in devices) else devices[0].device_id
            device_dropdown.value = selected_device
            device_dropdown.disabled = False
            device_dropdown.hint_text = "Selecciona un device"
            devices_total_text.value = f"Total devices: {len(devices)}"
            status_text.value = ""
            refresh_create_enabled()
            self.page.update()

        def load_devices() -> tuple[int, list[DeviceInfo]]:
            set_loading("Consultando devices disponibles...", True)
            self.set_sdk_root()
            code, devices, _output = self.avd_service.list_available_devices()
            return code, devices

        def submit(_e) -> None:
            name = name_field.value.strip()
            package = (images_dropdown.value or "").strip()
            device = (device_dropdown.value or "").strip()
            if not name or not package or not device:
                status_text.value = "Completa nombre, package y device."
                self.page.update()
                return

            self.set_sdk_root()
            self.log_expanded = True
            self.log_body.visible = True
            self.log_body.expand = True
            self.log_header_label.value = "Log expandido"
            self.log_header_icon.name = ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED
            self.log_panel.height = 360
            set_create_in_progress(True, "")
            self.log_queue.put(f"[create-avd] Solicitud recibida para '{name}'\n")
            self.log_queue.put(f"[create-avd] package={package}\n")
            self.log_queue.put(f"[create-avd] device={device} force={bool(force_checkbox.value)}\n")

            def on_exit(code: int) -> None:
                if code == 0:
                    self.log_queue.put("[create-avd] AVD creado correctamente.\n")
                    self.log_queue.put(f"__REFRESH_AVDS__:{name}\n")
                    self.log_queue.put(f"__CREATE_RESULT__:{name}:{code}\n")
                else:
                    self.log_queue.put("[create-avd] Falló la creación del AVD.\n")
                    self.log_queue.put(f"__CREATE_RESULT__:{name}:{code}\n")

            proc = self.avd_service.create_avd(
                name=name,
                package=package,
                device=device,
                force=bool(force_checkbox.value),
                on_exit=on_exit,
            )
            if proc is None:
                set_create_in_progress(False, "No se pudo iniciar el proceso.")
                return

            self.show_snackbar(f"Creando AVD {name}...")
            self.create_dialog_state = {
                "dialog": dialog,
                "set_create_in_progress": set_create_in_progress,
            }

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#111823",
            title=ft.Text("Crear nuevo AVD", color="#eff4fd", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                width=640,
                content=ft.Column(
                    controls=[
                        name_field,
                        ft.Column(controls=[images_total_text, images_dropdown, selected_package_text], spacing=8),
                        ft.Column(controls=[devices_total_text, device_dropdown], spacing=8),
                        loading_row,
                        create_progress,
                        force_checkbox,
                        status_text,
                    ],
                    tight=True,
                    spacing=18,
                ),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _e: self.close_dialog(dialog)),
                create_button,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        create_button.on_click = submit
        self.show_dialog(dialog)

        async def bootstrap_options() -> None:
            await asyncio.sleep(0.05)
            code, images = await asyncio.to_thread(load_images)
            apply_images_result(code, images)
            code, devices = await asyncio.to_thread(load_devices)
            apply_devices_result(code, devices)

        self.page.run_task(bootstrap_options)

    def _device_option_label(self, device: DeviceInfo) -> str:
        parts = [device.name, f"({device.device_id})"]
        if device.tag:
            parts.append(f"- {device.tag}")
        return " ".join(parts)

    def _apply_selected_device(self, _event: ft.ControlEvent) -> None:
        self.page.update()

    def open_edit_dialog(self, avd_name: str) -> None:
        config_path, config = self.avd_service.get_avd_config(avd_name)
        if not config_path:
            self.show_snackbar(f"No se encontró config.ini para {avd_name}.", error=True)
            return

        ram_field = ft.TextField(label="RAM (MB)", value=config.get("hw.ramSize", "2048"))
        heap_field = ft.TextField(label="VM Heap (MB)", value=config.get("vm.heapSize", "256"))
        partition_field = ft.TextField(label="Data partition", value=config.get("disk.dataPartition.size", "2G"))
        frame_dropdown = ft.Dropdown(
            label="Show device frame",
            value=config.get("showDeviceFrame", "yes"),
            options=[ft.dropdown.Option("yes"), ft.dropdown.Option("no")],
        )
        status_text = ft.Text("", color="#ef9090")

        def save(_e) -> None:
            ok, message = self.avd_service.update_avd_config(
                avd_name=avd_name,
                ram_mb=ram_field.value.strip(),
                heap_mb=heap_field.value.strip(),
                data_partition=partition_field.value.strip(),
                show_device_frame=frame_dropdown.value or "yes",
            )
            if not ok:
                status_text.value = message
                self.page.update()
                return

            self.close_dialog(dialog)
            self.refresh_avds()
            self.show_snackbar(message)

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#111823",
            title=ft.Text(f"Editar {avd_name}", color="#eff4fd", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                width=600,
                content=ft.Column(
                    controls=[
                        ft.Text(f"Archivo: {config_path}", color="#7c91b1", size=12, selectable=True),
                        ram_field,
                        heap_field,
                        partition_field,
                        frame_dropdown,
                        status_text,
                    ],
                    tight=True,
                    spacing=12,
                ),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _e: self.close_dialog(dialog)),
                ft.FilledButton("Guardar", on_click=save),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.show_dialog(dialog)

    def confirm_delete(self, avd_name: str) -> None:
        async def remove_async(avd_to_delete: str) -> None:
            code, _output = await asyncio.to_thread(self.avd_service.delete_avd, avd_to_delete)
            self.deleting_avd_names.discard(avd_to_delete)
            if code != 0:
                self.refresh_avds()
                self.show_snackbar(f"No se pudo eliminar {avd_to_delete}.", error=True)
                return
            self.refresh_avds()
            self.show_snackbar(f"{avd_to_delete} eliminado.")

        def remove(_e) -> None:
            self.close_dialog(dialog)
            self.set_sdk_root()
            self.deleting_avd_names.add(avd_name)
            self.refresh_avds()
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
        proc = self.avd_service.launch_emulator(avd_name)
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
                    self.log_lines.append(msg)
                    changed = True
                except queue.Empty:
                    break

            if changed:
                self.log_view.value = "".join(self.log_lines[-500:])
                self.page.update()

            if self.refresh_target_name and self.refresh_attempts_left > 0 and time.monotonic() >= self.next_refresh_at:
                self.refresh_avds()
                avd_names = {item.name for item in self.avd_items}
                if self.refresh_target_name in avd_names:
                    self.show_snackbar(f"{self.refresh_target_name} ya aparece en la lista.")
                    self.refresh_target_name = None
                    self.refresh_attempts_left = 0
                else:
                    self.refresh_attempts_left -= 1
                    self.next_refresh_at = time.monotonic() + 1.0

            await asyncio.sleep(0.2)


def main(page: ft.Page) -> None:
    FletAvdApp(page)


if __name__ == "__main__":
    ft.run(main, assets_dir=str(BASE_DIR))
