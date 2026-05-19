from __future__ import annotations

import asyncio
import time
from typing import Any

import flet as ft

from services.avd_service import DeviceInfo


def open_create_dialog(app: Any, _event) -> None:
    name_field = ft.TextField(label="Nombre", autofocus=True)
    force_checkbox = ft.Checkbox(label="Sobrescribir si existe", value=False)
    create_button = ft.FilledButton("Crear", disabled=True)
    duplicate_name_text = ft.Text("", color="#f0a54a", size=12)
    refresh_images_button = ft.IconButton(icon=ft.Icons.REFRESH_ROUNDED, tooltip="Recargar imágenes desde sdkmanager")
    refresh_devices_button = ft.IconButton(icon=ft.Icons.REFRESH_ROUNDED, tooltip="Recargar devices desde avdmanager")
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
        on_select=app._apply_selected_device,
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
    images_loaded_at_text = ft.Text("Última carga: --", color="#6f86a6", size=11)
    devices_loaded_at_text = ft.Text("Última carga: --", color="#6f86a6", size=11)
    selected_package_text = ft.Text(
        f"Package seleccionado: {app.config.get('last_image_package') or app.avd_service.default_image_package()}",
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
    existing_avd_names = {item.name for item in app.avd_items}

    def is_duplicate_name() -> bool:
        return bool(name_field.value.strip()) and name_field.value.strip() in existing_avd_names

    def refresh_create_enabled(_event=None) -> None:
        duplicate = is_duplicate_name()
        if duplicate and not force_checkbox.value:
            duplicate_name_text.value = "Ya existe un AVD con ese nombre. Activa 'Sobrescribir si existe' para continuar."
        elif duplicate and force_checkbox.value:
            duplicate_name_text.value = "El nombre ya existe; se intentará sobrescribir."
        else:
            duplicate_name_text.value = ""

        can_create = (
            bool(name_field.value.strip())
            and bool((images_dropdown.value or "").strip())
            and bool((device_dropdown.value or "").strip())
            and not creating_state["active"]
            and (not duplicate or bool(force_checkbox.value))
        )
        create_button.disabled = not can_create
        app.page.update()

    name_field.on_change = refresh_create_enabled
    force_checkbox.on_change = refresh_create_enabled

    def apply_selected_image(_event: ft.ControlEvent) -> None:
        selected = images_dropdown.value
        if selected:
            selected_package_text.value = f"Package seleccionado: {selected}"
            app.config["last_image_package"] = selected
            app.save_config()
            app.page.update()

    images_dropdown.on_select = apply_selected_image

    def set_create_in_progress(in_progress: bool, message: str = "") -> None:
        creating_state["active"] = in_progress
        name_field.disabled = in_progress
        images_dropdown.disabled = in_progress or not bool(images_dropdown.options)
        device_dropdown.disabled = in_progress or not bool(device_dropdown.options)
        force_checkbox.disabled = in_progress
        refresh_images_button.disabled = in_progress
        refresh_devices_button.disabled = in_progress
        create_button.text = "Creando..." if in_progress else "Crear"
        create_progress.visible = in_progress
        status_text.value = message
        refresh_create_enabled()
        app.page.update()

    def set_loading(message: str, visible: bool) -> None:
        if visible:
            loading_counter["count"] += 1
            loading_text.value = message
            loading_row.visible = True
            refresh_images_button.disabled = True
            refresh_devices_button.disabled = True
        else:
            loading_counter["count"] = max(0, loading_counter["count"] - 1)
            if loading_counter["count"] == 0:
                loading_text.value = ""
                loading_row.visible = False
                refresh_images_button.disabled = creating_state["active"]
                refresh_devices_button.disabled = creating_state["active"]
        app.page.update()

    def apply_images_result(code: int, images: list[str]) -> None:
        set_loading("", False)
        if code != 0:
            status_text.value = "No se pudieron listar las imágenes. Revisa el log."
            app.page.update()
            return
        if not images:
            status_text.value = "No se encontraron system images disponibles."
            app.page.update()
            return

        images_dropdown.options = [ft.dropdown.Option(image) for image in images]
        preferred_image = app.config.get("last_image_package") or app.avd_service.default_image_package()
        images_dropdown.value = preferred_image if preferred_image in images else images[0]
        images_dropdown.disabled = False
        images_dropdown.hint_text = "Selecciona una imagen"
        images_total_text.value = f"Total imágenes: {len(images)}"
        images_loaded_at_text.value = app._format_loaded_at(app.images_cache_time.get(app._images_cache_key()))
        selected_package_text.value = f"Package seleccionado: {images_dropdown.value}"
        app.config["last_image_package"] = images_dropdown.value
        app.save_config()
        status_text.value = ""
        refresh_create_enabled()
        app.page.update()

    def load_images(force_refresh: bool = False) -> tuple[int, list[str]]:
        set_loading("Consultando imágenes disponibles...", True)
        app.set_sdk_root()
        cache_key = app._images_cache_key()
        if not force_refresh and cache_key in app.images_cache:
            return 0, app.images_cache[cache_key]
        code, images, _output = app.avd_service.list_available_images(sdkmanager_bin=app.sdkmanager_path_field.value.strip())
        if code == 0:
            app.images_cache[cache_key] = images
            app.images_cache_time[cache_key] = time.time()
        return code, images

    def apply_devices_result(code: int, devices: list[DeviceInfo]) -> None:
        set_loading("", False)
        if code != 0:
            status_text.value = "No se pudieron listar los devices. Revisa el log."
            app.page.update()
            return
        if not devices:
            status_text.value = "No se encontraron devices disponibles."
            app.page.update()
            return

        device_dropdown.options = [ft.dropdown.Option(device.device_id, app._device_option_label(device)) for device in devices]
        preferred_device = app.config.get("last_device_id") or app.avd_service.default_device_id()
        selected_device = preferred_device if any(device.device_id == preferred_device for device in devices) else devices[0].device_id
        device_dropdown.value = selected_device
        device_dropdown.disabled = False
        device_dropdown.hint_text = "Selecciona un device"
        devices_total_text.value = f"Total devices: {len(devices)}"
        devices_loaded_at_text.value = app._format_loaded_at(app.devices_cache_time.get(app._devices_cache_key()))
        app.config["last_device_id"] = selected_device
        app.save_config()
        status_text.value = ""
        refresh_create_enabled()
        app.page.update()

    def load_devices(force_refresh: bool = False) -> tuple[int, list[DeviceInfo]]:
        set_loading("Consultando devices disponibles...", True)
        app.set_sdk_root()
        cache_key = app._devices_cache_key()
        if not force_refresh and cache_key in app.devices_cache:
            return 0, app.devices_cache[cache_key]
        code, devices, _output = app.avd_service.list_available_devices(avdmanager_bin=app.avdmanager_path_field.value.strip())
        if code == 0:
            app.devices_cache[cache_key] = devices
            app.devices_cache_time[cache_key] = time.time()
        return code, devices

    def submit(_e) -> None:
        name = name_field.value.strip()
        package = (images_dropdown.value or "").strip()
        device = (device_dropdown.value or "").strip()
        if not name or not package or not device:
            status_text.value = "Completa nombre, package y device."
            app.page.update()
            return
        if name in existing_avd_names and not force_checkbox.value:
            status_text.value = "Ese AVD ya existe. Marca 'Sobrescribir si existe' o usa otro nombre."
            app.page.update()
            return

        app.set_sdk_root()
        set_create_in_progress(True, "")
        app.log_queue.put(f"[create-avd] Solicitud recibida para '{name}'\n")
        app.log_queue.put(f"[create-avd] package={package}\n")
        app.log_queue.put(f"[create-avd] device={device} force={bool(force_checkbox.value)}\n")

        def on_exit(code: int) -> None:
            if code == 0:
                app.log_queue.put("[create-avd] AVD creado correctamente.\n")
                app.log_queue.put(f"__REFRESH_AVDS__:{name}\n")
                app.log_queue.put(f"__CREATE_RESULT__:{name}:{code}\n")
            else:
                app.log_queue.put("[create-avd] Falló la creación del AVD.\n")
                app.log_queue.put(f"__CREATE_RESULT__:{name}:{code}\n")

        proc = app.avd_service.create_avd(
            name=name,
            package=package,
            device=device,
            force=bool(force_checkbox.value),
            avdmanager_bin=app.avdmanager_path_field.value.strip(),
            on_exit=on_exit,
        )
        if proc is None:
            set_create_in_progress(False, "No se pudo iniciar el proceso.")
            return

        app.show_snackbar(f"Creando AVD {name}...")
        app.create_dialog_state = {
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
                    duplicate_name_text,
                    ft.Column(
                        controls=[
                            ft.Row(controls=[images_total_text, refresh_images_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            images_loaded_at_text,
                            images_dropdown,
                            selected_package_text,
                        ],
                        spacing=8,
                    ),
                    ft.Column(
                        controls=[
                            ft.Row(controls=[devices_total_text, refresh_devices_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            devices_loaded_at_text,
                            device_dropdown,
                        ],
                        spacing=8,
                    ),
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
            ft.TextButton("Cancelar", on_click=lambda _e: app.close_dialog(dialog)),
            create_button,
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    create_button.on_click = submit
    app.show_dialog(dialog)

    async def reload_images_task(force_refresh: bool) -> None:
        code, images = await asyncio.to_thread(load_images, force_refresh)
        apply_images_result(code, images)

    async def reload_devices_task(force_refresh: bool) -> None:
        code, devices = await asyncio.to_thread(load_devices, force_refresh)
        apply_devices_result(code, devices)

    def refresh_images(_e) -> None:
        async def task() -> None:
            await reload_images_task(True)

        app.page.run_task(task)

    def refresh_devices(_e) -> None:
        async def task() -> None:
            await reload_devices_task(True)

        app.page.run_task(task)

    refresh_images_button.on_click = refresh_images
    refresh_devices_button.on_click = refresh_devices

    async def bootstrap_options() -> None:
        await asyncio.sleep(0.05)
        code, images = await asyncio.to_thread(load_images, False)
        apply_images_result(code, images)
        code, devices = await asyncio.to_thread(load_devices, False)
        apply_devices_result(code, devices)

    app.page.run_task(bootstrap_options)
