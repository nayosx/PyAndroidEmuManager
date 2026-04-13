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
import shutil
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext


class StreamReader(threading.Thread):
    def __init__(self, pipe, output_queue: queue.Queue, prefix: str = ""):
        super().__init__(daemon=True)
        self.pipe = pipe
        self.output_queue = output_queue
        self.prefix = prefix

    def run(self) -> None:
        try:
            for line in iter(self.pipe.readline, ""):
                if not line:
                    break
                self.output_queue.put(f"{self.prefix}{line}")
        except Exception as exc:
            self.output_queue.put(f"[reader-error] {exc}\n")
        finally:
            try:
                self.pipe.close()
            except Exception:
                pass


class AndroidSdkPaths:
    def __init__(self, sdk_root: str):
        self.sdk_root = Path(sdk_root).expanduser()

    @staticmethod
    def default_sdk_root() -> str:
        env = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        if env:
            return env

        system = platform.system()
        home = Path.home()

        candidates = []
        if system == "Darwin":
            candidates = [
                home / "Library" / "Android" / "sdk",
            ]
        elif system == "Linux":
            candidates = [
                home / "Android" / "Sdk",
                home / "Android" / "sdk",
            ]
        elif system == "Windows":
            local = os.environ.get("LOCALAPPDATA")
            userprofile = os.environ.get("USERPROFILE")
            if local:
                candidates.append(Path(local) / "Android" / "Sdk")
            if userprofile:
                candidates.append(Path(userprofile) / "AppData" / "Local" / "Android" / "Sdk")

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return str(candidates[0] if candidates else home / "Android" / "Sdk")

    @staticmethod
    def _first_existing(paths: list[Path]) -> str:
        for path in paths:
            if path.exists():
                return str(path)
        return str(paths[0])

    def emulator_bin(self) -> str:
        system = platform.system()
        if system == "Windows":
            candidates = [
                self.sdk_root / "emulator" / "emulator.exe",
                self.sdk_root / "emulator" / "emulator",
            ]
        else:
            candidates = [
                self.sdk_root / "emulator" / "emulator",
                self.sdk_root / "emulator" / "emulator.exe",
            ]
        return self._first_existing(candidates)

    def avdmanager_bin(self) -> str:
        system = platform.system()
        if system == "Windows":
            candidates = [
                self.sdk_root / "cmdline-tools" / "latest" / "bin" / "avdmanager.bat",
                self.sdk_root / "cmdline-tools" / "latest" / "bin" / "avdmanager.exe",
                self.sdk_root / "tools" / "bin" / "avdmanager.bat",
            ]
        else:
            candidates = [
                self.sdk_root / "cmdline-tools" / "latest" / "bin" / "avdmanager",
                self.sdk_root / "tools" / "bin" / "avdmanager",
            ]
        return self._first_existing(candidates)

    def sdkmanager_bin(self) -> str:
        system = platform.system()
        if system == "Windows":
            candidates = [
                self.sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat",
                self.sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager.exe",
                self.sdk_root / "tools" / "bin" / "sdkmanager.bat",
            ]
        else:
            candidates = [
                self.sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager",
                self.sdk_root / "tools" / "bin" / "sdkmanager",
            ]
        return self._first_existing(candidates)

    def platform_tools_dir(self) -> str:
        return str(self.sdk_root / "platform-tools")

    def emulator_dir(self) -> str:
        return str(self.sdk_root / "emulator")

    def cmdline_tools_dir(self) -> str:
        latest = self.sdk_root / "cmdline-tools" / "latest" / "bin"
        legacy = self.sdk_root / "tools" / "bin"
        if latest.exists():
            return str(latest)
        return str(legacy)


class EmulatorManagerApp(tk.Tk):
    POLL_MS = 120

    def __init__(self) -> None:
        super().__init__()
        self.title("Android Emulator Manager")
        self.geometry("1180x760")
        self.minsize(980, 640)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.emulator_process: subprocess.Popen | None = None

        self.android_sdk_root_var = tk.StringVar(value=AndroidSdkPaths.default_sdk_root())
        self.emulator_bin_var = tk.StringVar()
        self.avdmanager_bin_var = tk.StringVar()
        self.sdkmanager_bin_var = tk.StringVar()
        self.os_var = tk.StringVar(value=platform.system())

        self.selected_avd_var = tk.StringVar()
        self.create_name_var = tk.StringVar()
        self.create_package_var = tk.StringVar(value=self._default_image_package())
        self.create_device_var = tk.StringVar(value=self._default_device_id())
        self.create_force_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._refresh_derived_paths()
        self.after(100, self._poll_log_queue)
        self.after(150, self._initial_load)

    def _default_image_package(self) -> str:
        if platform.system() == "Windows":
            return "system-images;android-33;google_apis_playstore;x86_64"
        if platform.system() == "Linux":
            return "system-images;android-33;google_apis_playstore;x86_64"
        return "system-images;android-33;google_apis_playstore;arm64-v8a"

    def _default_device_id(self) -> str:
        return "pixel_3a"


    def _initial_load(self) -> None:
        self._append_log("[startup] Verificando rutas iniciales y cargando AVDs...\n")
        self.verify_paths()

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=10)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Sistema operativo").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(header, textvariable=self.os_var, state="readonly").grid(row=0, column=1, sticky="ew")

        ttk.Label(header, text="Android SDK Root").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        sdk_entry = ttk.Entry(header, textvariable=self.android_sdk_root_var)
        sdk_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(header, text="Recalcular rutas", command=self._refresh_derived_paths).grid(row=1, column=2, padx=(8, 0), pady=(8, 0))
        ttk.Button(header, text="Verificar rutas", command=self.verify_paths).grid(row=1, column=3, padx=(8, 0), pady=(8, 0))
        ttk.Button(header, text="Refrescar AVDs", command=self.list_avds).grid(row=1, column=4, padx=(8, 0), pady=(8, 0))

        middle = ttk.Panedwindow(self, orient="horizontal")
        middle.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.rowconfigure(1, weight=1)

        left = ttk.Frame(middle, padding=8)
        right = ttk.Frame(middle, padding=8)
        middle.add(left, weight=2)
        middle.add(right, weight=3)

        self._build_left_panel(left)
        self._build_right_panel(right)

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.grid(row=2, column=0, sticky="nsew")
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(1, weight=1)

        ttk.Label(bottom, text="Log del emulador / comandos").grid(row=0, column=0, sticky="w")
        self.log_text = scrolledtext.ScrolledText(bottom, wrap="word", height=18)
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.log_text.configure(font=("Menlo", 11))

        self._append_log("Aplicación iniciada.\n")
        self._append_log("Enfoque: Android SDK solamente.\n")

    def _build_left_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        for r in range(12):
            parent.rowconfigure(r, weight=0)
        parent.rowconfigure(11, weight=1)

        ttk.Label(parent, text="Binarios detectados", font=("", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(parent, text="emulator").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(parent, textvariable=self.emulator_bin_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(parent, text="avdmanager").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(parent, textvariable=self.avdmanager_bin_var).grid(row=2, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(parent, text="sdkmanager").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(parent, textvariable=self.sdkmanager_bin_var).grid(row=3, column=1, sticky="ew", pady=(6, 0))

        ttk.Separator(parent).grid(row=4, column=0, columnspan=2, sticky="ew", pady=12)

        ttk.Label(parent, text="AVDs disponibles", font=("", 11, "bold")).grid(row=5, column=0, columnspan=2, sticky="w")
        self.avd_listbox = tk.Listbox(parent, height=10, exportselection=False)
        self.avd_listbox.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(8, 8))
        self.avd_listbox.bind("<<ListboxSelect>>", self._on_avd_select)
        self.avd_listbox.bind("<Double-Button-1>", lambda _e: self.launch_emulator())

        launch_frame = ttk.Frame(parent)
        launch_frame.grid(row=7, column=0, columnspan=2, sticky="ew")
        launch_frame.columnconfigure(1, weight=1)

        ttk.Label(launch_frame, text="AVD seleccionado").grid(row=0, column=0, sticky="w")
        ttk.Entry(launch_frame, textvariable=self.selected_avd_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(launch_frame, text="Lanzar", command=self.launch_emulator).grid(row=0, column=2)
        ttk.Button(launch_frame, text="Detener", command=self.stop_emulator).grid(row=0, column=3, padx=(8, 0))

        opts = ttk.LabelFrame(parent, text="Opciones rápidas de arranque", padding=8)
        opts.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        opts.columnconfigure(1, weight=1)

        self.wipe_var = tk.BooleanVar(value=False)
        self.no_snapshot_var = tk.BooleanVar(value=False)
        self.no_boot_anim_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(opts, text="Wipe data", variable=self.wipe_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(opts, text="No snapshot", variable=self.no_snapshot_var).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(opts, text="No boot anim", variable=self.no_boot_anim_var).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(opts, text="Verbose", variable=self.verbose_var).grid(row=1, column=1, sticky="w")

    def _build_right_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="Crear nuevo AVD", font=("", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(parent, text="Nombre").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(parent, textvariable=self.create_name_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(parent, text="System image package").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(parent, textvariable=self.create_package_var).grid(row=2, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(parent, text="Device id").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(parent, textvariable=self.create_device_var).grid(row=3, column=1, sticky="ew", pady=(6, 0))

        ttk.Checkbutton(parent, text="Sobrescribir si existe", variable=self.create_force_var).grid(
            row=4, column=1, sticky="w", pady=(8, 0)
        )

        button_row = ttk.Frame(parent)
        button_row.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(button_row, text="Crear AVD", command=self.create_avd).pack(side="left")
        ttk.Button(button_row, text="Listar devices", command=self.list_devices).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="Listar images", command=self.list_images).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="Limpiar log", command=self.clear_log).pack(side="left", padx=(8, 0))

        info = ttk.LabelFrame(parent, text="Ayuda", padding=8)
        info.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(16, 0))
        info.columnconfigure(0, weight=1)

        help_text = (
            "Flujo recomendado:\n"
            "1. Verifica rutas.\n"
            "2. Refresca AVDs.\n"
            "3. Selecciona y lanza un emulador.\n"
            "4. Si necesitas uno nuevo, crea un AVD con avdmanager.\n\n"
            "Ejemplos de package:\n"
            "macOS Apple Silicon: system-images;android-33;google_apis_playstore;arm64-v8a\n"
            "Linux / Windows: system-images;android-33;google_apis_playstore;x86_64\n\n"
            "Ejemplo de device id:\n"
            "pixel_3a\n"
        )
        ttk.Label(info, text=help_text, justify="left").grid(row=0, column=0, sticky="nw")

    # ---------------- Helpers ----------------

    def _refresh_derived_paths(self) -> None:
        paths = AndroidSdkPaths(self.android_sdk_root_var.get())
        self.emulator_bin_var.set(paths.emulator_bin())
        self.avdmanager_bin_var.set(paths.avdmanager_bin())
        self.sdkmanager_bin_var.set(paths.sdkmanager_bin())

    def _append_log(self, text: str) -> None:
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._poll_log_queue)

    def _on_avd_select(self, _event=None) -> None:
        selection = self.avd_listbox.curselection()
        if not selection:
            return
        name = self.avd_listbox.get(selection[0])
        self.selected_avd_var.set(name)

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        sdk_root = self.android_sdk_root_var.get().strip()
        paths = AndroidSdkPaths(sdk_root)

        env["ANDROID_SDK_ROOT"] = sdk_root
        env["ANDROID_HOME"] = sdk_root

        prepend_paths = [
            paths.emulator_dir(),
            paths.platform_tools_dir(),
            paths.cmdline_tools_dir(),
        ]

        env["PATH"] = os.pathsep.join(prepend_paths + [env.get("PATH", "")])
        return env

    def _run_sync(self, cmd: list[str], title: str) -> tuple[int, str]:
        try:
            self._append_log(f"\n[{title}] Ejecutando: {' '.join(cmd)}\n")
            proc = subprocess.run(
                cmd,
                env=self._build_env(),
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            if output:
                self._append_log(output + ("\n" if not output.endswith("\n") else ""))
            self._append_log(f"[{title}] exit={proc.returncode}\n")
            return proc.returncode, output
        except Exception as exc:
            msg = f"[{title}] error: {exc}\n"
            self._append_log(msg)
            return 1, msg

    def _run_async(self, cmd: list[str], title: str, cwd: str | None = None) -> subprocess.Popen | None:
        try:
            self._append_log(f"\n[{title}] Ejecutando: {' '.join(cmd)}\n")
            if cwd:
                self._append_log(f"[{title}] cwd={cwd}\n")

            creationflags = 0
            if platform.system() == "Windows":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                cmd,
                env=self._build_env(),
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                shell=False,
                creationflags=creationflags,
            )
            if proc.stdout:
                StreamReader(proc.stdout, self.log_queue).start()

            def waiter() -> None:
                code = proc.wait()
                self.log_queue.put(f"[{title}] exit={code}\n")

            threading.Thread(target=waiter, daemon=True).start()
            return proc
        except Exception as exc:
            self._append_log(f"[{title}] error: {exc}\n")
            return None

    # ---------------- Actions ----------------

    def verify_paths(self) -> None:
        self._refresh_derived_paths()
        self._append_log("\n[verify] Verificando rutas...\n")

        checks = [
            ("ANDROID_SDK_ROOT", self.android_sdk_root_var.get()),
            ("emulator", self.emulator_bin_var.get()),
            ("avdmanager", self.avdmanager_bin_var.get()),
            ("sdkmanager", self.sdkmanager_bin_var.get()),
        ]

        for label, raw_path in checks:
            path = Path(raw_path).expanduser()
            exists = path.exists()
            status = "OK" if exists else "MISSING"
            self._append_log(f"[verify] {label}: {path} -> {status}\n")

        emulator_on_path = shutil.which(Path(self.emulator_bin_var.get()).name, path=self._build_env().get("PATH"))
        avd_name = Path(self.avdmanager_bin_var.get()).name
        sdk_name = Path(self.sdkmanager_bin_var.get()).name
        avd_on_path = shutil.which(avd_name, path=self._build_env().get("PATH"))
        sdk_on_path = shutil.which(sdk_name, path=self._build_env().get("PATH"))

        self._append_log(f"[verify] which emulator -> {emulator_on_path}\n")
        self._append_log(f"[verify] which {avd_name} -> {avd_on_path}\n")
        self._append_log(f"[verify] which {sdk_name} -> {sdk_on_path}\n")

        self.list_avds(show_popup=False)

    def list_avds(self, show_popup: bool = False) -> None:
        emulator_bin = self.emulator_bin_var.get().strip()
        if not Path(emulator_bin).exists():
            messagebox.showerror("Ruta inválida", "No se encontró el binario emulator.")
            return

        code, output = self._run_sync([emulator_bin, "-list-avds"], "list-avds")
        if code != 0:
            messagebox.showerror("Error", "No se pudieron listar los AVDs. Revisa el log.")
            return

        avds = [line.strip() for line in output.splitlines() if line.strip() and not line.startswith("[")]
        self.avd_listbox.delete(0, "end")
        for avd in avds:
            self.avd_listbox.insert("end", avd)

        if avds and not self.selected_avd_var.get():
            self.selected_avd_var.set(avds[0])

        if show_popup:
            messagebox.showinfo("AVDs", f"Se encontraron {len(avds)} AVD(s).")

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

        emulator_dir = str(Path(emulator_bin).resolve().parent)
        cmd = [emulator_bin, "-avd", avd_name]

        if self.wipe_var.get():
            cmd.append("-wipe-data")
        if self.no_snapshot_var.get():
            cmd.append("-no-snapshot")
        if self.no_boot_anim_var.get():
            cmd.append("-no-boot-anim")
        if self.verbose_var.get():
            cmd.append("-verbose")

        proc = self._run_async(cmd, f"launch:{avd_name}", cwd=emulator_dir)
        if proc is None:
            messagebox.showerror("Error", "No se pudo iniciar el emulador.")
            return

        self.emulator_process = proc
        self._append_log(f"[launch:{avd_name}] PID={proc.pid}\n")
        self._append_log(f"[launch:{avd_name}] Esperando salida del proceso...\n")

    def stop_emulator(self) -> None:
        proc = self.emulator_process
        if not proc or proc.poll() is not None:
            self._append_log("[stop] No hay emulador activo lanzado desde esta UI.\n")
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

    def list_devices(self) -> None:
        avdmanager_bin = self.avdmanager_bin_var.get().strip()
        if not Path(avdmanager_bin).exists():
            messagebox.showerror("Ruta inválida", "No se encontró avdmanager.")
            return
        self._run_sync([avdmanager_bin, "list", "device"], "avdmanager-list-device")

    def list_images(self) -> None:
        sdkmanager_bin = self.sdkmanager_bin_var.get().strip()
        if not Path(sdkmanager_bin).exists():
            messagebox.showerror("Ruta inválida", "No se encontró sdkmanager.")
            return
        self._run_sync([sdkmanager_bin, "--list"], "sdkmanager-list")

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

        cmd = [avdmanager_bin, "create", "avd", "-n", name, "-k", package, "-d", device]
        if self.create_force_var.get():
            cmd.append("-f")

        self._append_log("\n[create-avd] Nota: si la imagen no existe, primero instálala con sdkmanager.\n")
        self._append_log(f"[create-avd] package={package} device={device} name={name}\n")

        try:
            creationflags = 0
            if platform.system() == "Windows":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                cmd,
                env=self._build_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                shell=False,
                creationflags=creationflags,
            )

            if proc.stdin:
                proc.stdin.write("no\n")
                proc.stdin.flush()
                proc.stdin.close()

            if proc.stdout:
                StreamReader(proc.stdout, self.log_queue).start()

            def waiter() -> None:
                code = proc.wait()
                self.log_queue.put(f"[create-avd] exit={code}\n")
                if code == 0:
                    self.log_queue.put("[create-avd] AVD creado correctamente.\n")
                    self.after(0, self.list_avds)
                else:
                    self.log_queue.put("[create-avd] Falló la creación del AVD.\n")

            threading.Thread(target=waiter, daemon=True).start()

        except Exception as exc:
            self._append_log(f"[create-avd] error: {exc}\n")


def main() -> None:
    app = EmulatorManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
