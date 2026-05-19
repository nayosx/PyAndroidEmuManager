from __future__ import annotations

from typing import Any

import flet as ft

from services.avd_service import AvdInfo


def build_avd_card(app: Any, item: AvdInfo, border_builder) -> ft.Control:
    is_deleting = item.name in app.deleting_avd_names
    status_color = "#2bb673" if item.is_running else "#41d391" if item.status == "Ready" else "#f0a54a"
    status_label = "Running" if item.is_running else item.status
    details = [
        f"RAM {item.ram_mb} MB" if item.ram_mb else None,
        f"Heap {item.heap_mb} MB" if item.heap_mb else None,
        f"Data {item.data_partition}" if item.data_partition else None,
    ]
    detail_text = "  |  ".join(part for part in details if part)

    meta_lines = []
    if item.device_name:
        meta_lines.append(ft.Text(item.device_name, color="#dbe8ff", size=12))
    if item.image_label:
        meta_lines.append(ft.Text(item.image_label, color="#8fa4c2", size=12))
    if detail_text:
        meta_lines.append(ft.Text(detail_text, color="#7c91b1", size=11))

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
                                ft.Icon(ft.Icons.CIRCLE, size=12, color=status_color),
                                ft.Text(status_label, color="#8fa4c2", size=13),
                            ],
                            spacing=8,
                        ),
                        *meta_lines,
                    ],
                    spacing=6,
                    expand=True,
                ),
                ft.Row(
                    controls=[
                        ft.FilledButton(
                            "Lanzar",
                            icon=ft.Icons.PLAY_ARROW_ROUNDED,
                            on_click=lambda _e, avd=item.name: app.launch_avd(avd),
                            disabled=is_deleting or item.is_running,
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
                            on_click=lambda _e, avd=item.name: app.open_edit_dialog(avd),
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
                                on_click=lambda _e, avd=item.name: app.confirm_delete(avd),
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
        border=border_builder(1, "#263448"),
        padding=18,
    )
