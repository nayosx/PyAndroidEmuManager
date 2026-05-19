from __future__ import annotations

from typing import Any

import flet as ft


def open_edit_dialog(app: Any, avd_name: str) -> None:
    config_path, config = app.avd_service.get_editable_avd_config(avd_name)
    if not config_path:
        app.show_snackbar(f"No se encontró config.ini para {avd_name}.", error=True)
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
    initial_values = {
        "hw.ramSize": config.get("hw.ramSize", "2048"),
        "vm.heapSize": config.get("vm.heapSize", "256"),
        "disk.dataPartition.size": config.get("disk.dataPartition.size", "2G"),
        "showDeviceFrame": config.get("showDeviceFrame", "yes"),
    }

    def save(_e) -> None:
        ok, updates, message = app.avd_service.normalize_avd_config_inputs(
            ram_mb=ram_field.value.strip(),
            heap_mb=heap_field.value.strip(),
            data_partition=partition_field.value.strip(),
            show_device_frame=frame_dropdown.value or "yes",
        )
        if not ok:
            status_text.value = message
            app.page.update()
            return

        if updates == initial_values:
            app.close_dialog(dialog)
            return

        ok, message = app.avd_service.update_avd_config(
            avd_name=avd_name,
            ram_mb=updates["hw.ramSize"],
            heap_mb=updates["vm.heapSize"],
            data_partition=updates["disk.dataPartition.size"],
            show_device_frame=updates["showDeviceFrame"],
        )
        if not ok:
            status_text.value = message
            app.page.update()
            return

        app.close_dialog(dialog)
        app.refresh_avds(force_refresh=True)
        app.show_snackbar(message)

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
            ft.TextButton("Cancelar", on_click=lambda _e: app.close_dialog(dialog)),
            ft.FilledButton("Guardar", on_click=save),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    app.show_dialog(dialog)
