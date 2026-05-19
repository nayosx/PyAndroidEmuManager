from __future__ import annotations

from typing import Any

import flet as ft

from widgets import build_avd_card


def build_empty_state() -> ft.Control:
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


def build_dashboard_view(app: Any, border_builder) -> ft.Control:
    app.cards_column.controls = [build_avd_card(app, item, border_builder) for item in app.avd_items] or [build_empty_state()]
    return ft.Container(
        content=app.cards_column,
        expand=True,
        border_radius=24,
        bgcolor="#101721",
        border=border_builder(1, "#223041"),
        padding=18,
    )
