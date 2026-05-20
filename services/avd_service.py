from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from services.process_runner import ProcessRunner
from services.sdk_paths import AndroidSdkPaths


@dataclass
class PathCheck:
    label: str
    path: Path
    exists: bool


@dataclass
class VerifyReport:
    checks: list[PathCheck]
    emulator_on_path: str | None
    avdmanager_on_path: str | None
    sdkmanager_on_path: str | None


@dataclass
class AvdInfo:
    name: str
    status: str
    config_path: Path | None
    is_running: bool = False
    ram_mb: str | None = None
    heap_mb: str | None = None
    data_partition: str | None = None
    image_label: str | None = None
    device_name: str | None = None


@dataclass
class DeviceInfo:
    device_id: str
    name: str
    oem: str | None = None
    tag: str | None = None


@dataclass
class ImagePackageInfo:
    package: str
    installed: bool
    updatable: bool = False
    version: str | None = None
    description: str | None = None


@dataclass
class BinaryStatus:
    label: str
    path: str
    exists: bool
    executable: bool
    usable: bool
    detail: str


@dataclass
class EnvironmentStatus:
    sdk_root: str
    os_name: str
    emulator: BinaryStatus
    avdmanager: BinaryStatus
    sdkmanager: BinaryStatus
    can_list_avds: bool
    can_launch: bool
    can_create: bool
    can_edit: bool
    can_delete: bool
    can_list_images: bool
    can_list_devices: bool
    is_ready: bool
    needs_setup: bool
    is_partial: bool
    summary: str


class AvdService:
    def __init__(self, runner: ProcessRunner):
        self.runner = runner

    @staticmethod
    def default_image_package() -> str:
        if platform.system() == "Windows":
            return "system-images;android-33;google_apis_playstore;x86_64"
        if platform.system() == "Linux":
            return "system-images;android-33;google_apis_playstore;x86_64"
        return "system-images;android-33;google_apis;arm64-v8a"

    @staticmethod
    def default_device_id() -> str:
        return "pixel_3a"

    def set_sdk_root(self, sdk_root: str) -> None:
        self.runner.set_sdk_root(sdk_root)

    def sdk_paths(self) -> AndroidSdkPaths:
        return AndroidSdkPaths(self.runner.sdk_root)

    def derived_paths(self) -> dict[str, str]:
        paths = self.sdk_paths()
        return {
            "emulator": paths.emulator_bin(),
            "avdmanager": paths.avdmanager_bin(),
            "sdkmanager": paths.sdkmanager_bin(),
            "adb": paths.adb_bin(),
        }

    def _probe_binary(self, label: str, path: str, cmd: list[str], sdk_root: str) -> BinaryStatus:
        candidate = Path(path).expanduser()
        exists = candidate.exists()
        executable = exists and os.access(candidate, os.X_OK)
        if not exists:
            return BinaryStatus(label=label, path=str(candidate), exists=False, executable=False, usable=False, detail="No existe")
        if not executable:
            return BinaryStatus(label=label, path=str(candidate), exists=True, executable=False, usable=False, detail="No es ejecutable")

        env = self.runner.build_env().copy()
        env["ANDROID_SDK_ROOT"] = sdk_root
        env["ANDROID_HOME"] = sdk_root

        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False, shell=False)
            usable = proc.returncode == 0
            detail = "OK" if usable else f"exit={proc.returncode}"
            return BinaryStatus(label=label, path=str(candidate), exists=True, executable=True, usable=usable, detail=detail)
        except Exception as exc:
            return BinaryStatus(label=label, path=str(candidate), exists=True, executable=True, usable=False, detail=str(exc))

    def validate_environment(
        self,
        sdk_root: str | None = None,
        emulator_path: str | None = None,
        avdmanager_path: str | None = None,
        sdkmanager_path: str | None = None,
        deep: bool = False,
    ) -> EnvironmentStatus:
        sdk_root = (sdk_root or self.runner.sdk_root).strip()
        original_root = self.runner.sdk_root
        self.runner.set_sdk_root(sdk_root)
        derived = self.derived_paths()

        emulator_path = (emulator_path or derived["emulator"]).strip()
        avdmanager_path = (avdmanager_path or derived["avdmanager"]).strip()
        sdkmanager_path = (sdkmanager_path or derived["sdkmanager"]).strip()

        emulator_cmd = [emulator_path, "-list-avds"] if deep else [emulator_path, "-version"]
        avdmanager_cmd = [avdmanager_path, "list", "device"] if deep else [avdmanager_path, "list", "target"]
        sdkmanager_cmd = [sdkmanager_path, "--list"] if deep else [sdkmanager_path, "--version"]

        emulator = self._probe_binary("emulator", emulator_path, emulator_cmd, sdk_root)
        avdmanager = self._probe_binary("avdmanager", avdmanager_path, avdmanager_cmd, sdk_root)
        sdkmanager = self._probe_binary("sdkmanager", sdkmanager_path, sdkmanager_cmd, sdk_root)

        sdk_exists = bool(sdk_root) and Path(sdk_root).expanduser().exists()
        can_list_avds = emulator.usable
        can_launch = emulator.usable
        can_create = avdmanager.usable
        can_edit = True
        can_delete = avdmanager.usable
        can_list_images = sdkmanager.usable
        can_list_devices = avdmanager.usable

        is_ready = sdk_exists and can_list_avds and can_create and can_list_images
        any_usable = can_list_avds or can_create or can_list_images
        needs_setup = not sdk_exists or not any_usable
        is_partial = not is_ready and any_usable

        if is_ready:
            summary = "Entorno listo." if deep else "Entorno listo (validación rápida)."
        elif needs_setup:
            summary = "Faltan rutas o binarios clave del Android SDK."
        else:
            missing = []
            if not can_list_avds:
                missing.append("emulator")
            if not can_create:
                missing.append("avdmanager")
            if not can_list_images:
                missing.append("sdkmanager")
            summary = f"Entorno parcial. Faltan capacidades: {', '.join(missing)}."

        self.runner.set_sdk_root(original_root)
        return EnvironmentStatus(
            sdk_root=sdk_root,
            os_name=platform.system(),
            emulator=emulator,
            avdmanager=avdmanager,
            sdkmanager=sdkmanager,
            can_list_avds=can_list_avds,
            can_launch=can_launch,
            can_create=can_create,
            can_edit=can_edit,
            can_delete=can_delete,
            can_list_images=can_list_images,
            can_list_devices=can_list_devices,
            is_ready=is_ready,
            needs_setup=needs_setup,
            is_partial=is_partial,
            summary=summary,
        )

    def verify_paths(self) -> VerifyReport:
        derived = self.derived_paths()
        checks = [
            PathCheck("ANDROID_SDK_ROOT", Path(self.runner.sdk_root).expanduser(), Path(self.runner.sdk_root).expanduser().exists()),
            PathCheck("emulator", Path(derived["emulator"]).expanduser(), Path(derived["emulator"]).expanduser().exists()),
            PathCheck("avdmanager", Path(derived["avdmanager"]).expanduser(), Path(derived["avdmanager"]).expanduser().exists()),
            PathCheck("sdkmanager", Path(derived["sdkmanager"]).expanduser(), Path(derived["sdkmanager"]).expanduser().exists()),
        ]

        env_path = self.runner.build_env().get("PATH")
        avd_name = Path(derived["avdmanager"]).name
        sdk_name = Path(derived["sdkmanager"]).name

        return VerifyReport(
            checks=checks,
            emulator_on_path=shutil.which(Path(derived["emulator"]).name, path=env_path),
            avdmanager_on_path=shutil.which(avd_name, path=env_path),
            sdkmanager_on_path=shutil.which(sdk_name, path=env_path),
        )

    def android_avd_home(self) -> Path:
        return Path(self.runner.build_env().get("ANDROID_AVD_HOME") or (Path.home() / ".android" / "avd")).expanduser()

    def avd_ini_path(self, avd_name: str) -> Path:
        return self.android_avd_home() / f"{avd_name}.ini"

    def avd_config_path(self, avd_name: str) -> Path | None:
        ini_path = self.avd_ini_path(avd_name)
        if not ini_path.exists():
            return None

        try:
            for line in ini_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("path="):
                    avd_dir = Path(line.split("=", 1)[1].strip()).expanduser()
                    config_path = avd_dir / "config.ini"
                    if config_path.exists():
                        return config_path
        except Exception as exc:
            self.runner.output_queue.put(f"[avd-config] No se pudo leer {ini_path}: {exc}\n")
        return None

    def avd_status(self, avd_name: str) -> str:
        return "Ready" if self.avd_config_path(avd_name) else "Missing config"

    def list_avd_info(self, emulator_bin: str | None = None) -> tuple[int, list[AvdInfo], str]:
        code, avds, output = self.list_avds(emulator_bin=emulator_bin)
        running_avds = self.running_avd_names()
        info = []
        for avd in avds:
            config_path = self.avd_config_path(avd)
            metadata = self.read_avd_metadata(config_path) if config_path else {}
            is_running = avd in running_avds
            info.append(
                AvdInfo(
                    name=avd,
                    status="Running" if is_running else self.avd_status(avd),
                    config_path=config_path,
                    is_running=is_running,
                    ram_mb=metadata.get("hw.ramSize"),
                    heap_mb=metadata.get("vm.heapSize"),
                    data_partition=metadata.get("disk.dataPartition.size"),
                    image_label=metadata.get("image_label"),
                    device_name=metadata.get("hw.device.name"),
                )
            )
        return code, info, output

    def _run_quiet(self, cmd: list[str]) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                cmd,
                env=self.runner.build_env(),
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except Exception:
            return 1, ""

    def running_avd_names(self, adb_bin: str | None = None) -> set[str]:
        adb_bin = (adb_bin or self.derived_paths()["adb"]).strip()
        code, output = self._run_quiet([adb_bin, "devices"])
        if code != 0:
            return set()

        running: set[str] = set()
        serials: list[str] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("List of devices attached"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("emulator-") and parts[1] == "device":
                serials.append(parts[0])

        for serial in serials:
            code, avd_output = self._run_quiet([adb_bin, "-s", serial, "emu", "avd", "name"])
            if code != 0:
                continue
            avd_name = avd_output.strip()
            if avd_name:
                running.add(avd_name)
        return running

    def read_avd_metadata(self, config_path: Path) -> dict[str, str]:
        config = self.read_kv_file(config_path)
        metadata = {
            "hw.ramSize": self._normalize_mb_value(config.get("hw.ramSize"), "2048"),
            "vm.heapSize": self._normalize_mb_value(config.get("vm.heapSize"), "256"),
            "disk.dataPartition.size": self._normalize_partition_value(config.get("disk.dataPartition.size"), "2G"),
            "hw.device.name": config.get("hw.device.name", "").strip() or config.get("hw.device", "").strip(),
            "image_label": self._format_image_label(config),
        }
        return metadata

    @staticmethod
    def _format_image_label(config: dict[str, str]) -> str:
        image_sysdir = config.get("image.sysdir.1", "").strip().strip("/")
        if image_sysdir:
            parts = [part for part in Path(image_sysdir).parts if part and part != "system-images"]
            if parts:
                return " · ".join(parts)

        tag = config.get("tag.id", "").strip()
        abi = config.get("abi.type", "").strip()
        if tag and abi:
            return f"{tag} · {abi}"
        return tag or abi or "Imagen no detectada"

    def read_kv_file(self, path: Path) -> dict[str, str]:
        data: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
        return data

    def write_kv_file(self, path: Path, updates: dict[str, str]) -> None:
        lines = []
        seen: set[str] = set()
        existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

        for line in existing:
            if "=" not in line or line.lstrip().startswith("#"):
                lines.append(line)
                continue
            key, _value = line.split("=", 1)
            key = key.strip()
            if key in updates:
                lines.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                lines.append(line)

        for key, value in updates.items():
            if key not in seen:
                lines.append(f"{key}={value}")

        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def get_avd_config(self, avd_name: str) -> tuple[Path | None, dict[str, str]]:
        config_path = self.avd_config_path(avd_name)
        if not config_path:
            return None, {}
        return config_path, self.read_kv_file(config_path)

    @staticmethod
    def _normalize_mb_value(value: str | None, default: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return default

        match = re.fullmatch(r"(\d+)\s*(?:m|mb)?", raw, re.IGNORECASE)
        if match:
            return match.group(1)

        digits = re.search(r"(\d+)", raw)
        if digits:
            return digits.group(1)
        return default

    @staticmethod
    def _normalize_partition_value(value: str | None, default: str) -> str:
        raw = (value or "").strip().upper()
        if not raw:
            return default

        if re.fullmatch(r"\d+[MG]", raw, re.IGNORECASE):
            return raw

        if raw.isdigit():
            bytes_value = int(raw)
            gib = 1024 ** 3
            mib = 1024 ** 2
            if bytes_value >= gib and bytes_value % gib == 0:
                return f"{bytes_value // gib}G"
            if bytes_value >= mib and bytes_value % mib == 0:
                return f"{bytes_value // mib}M"
        return default

    @staticmethod
    def _normalize_frame_value(value: str | None, default: str = "yes") -> str:
        raw = (value or "").strip().lower()
        return raw if raw in {"yes", "no"} else default

    def get_editable_avd_config(self, avd_name: str) -> tuple[Path | None, dict[str, str]]:
        config_path, config = self.get_avd_config(avd_name)
        if not config_path:
            return None, {}

        return config_path, {
            "hw.ramSize": self._normalize_mb_value(config.get("hw.ramSize"), "2048"),
            "vm.heapSize": self._normalize_mb_value(config.get("vm.heapSize"), "256"),
            "disk.dataPartition.size": self._normalize_partition_value(config.get("disk.dataPartition.size"), "2G"),
            "showDeviceFrame": self._normalize_frame_value(config.get("showDeviceFrame"), "yes"),
        }

    def normalize_avd_config_inputs(
        self,
        ram_mb: str,
        heap_mb: str,
        data_partition: str,
        show_device_frame: str,
    ) -> tuple[bool, dict[str, str] | None, str]:
        ram = ram_mb.strip()
        heap = heap_mb.strip()
        partition = data_partition.strip().upper()
        frame = show_device_frame.strip().lower()

        if not ram.isdigit() or not heap.isdigit():
            return False, None, "RAM y VM Heap deben ser enteros."
        if not re.fullmatch(r"\d+[MG]", partition, re.IGNORECASE):
            return False, None, "Data partition debe verse como 2G o 512M."
        if frame not in {"yes", "no"}:
            return False, None, "Show device frame debe ser yes o no."

        return True, {
            "hw.ramSize": ram,
            "vm.heapSize": heap,
            "disk.dataPartition.size": partition,
            "showDeviceFrame": frame,
        }, ""

    def update_avd_config(
        self,
        avd_name: str,
        ram_mb: str,
        heap_mb: str,
        data_partition: str,
        show_device_frame: str,
    ) -> tuple[bool, str]:
        config_path = self.avd_config_path(avd_name)
        if not config_path:
            return False, f"No se encontró config.ini para {avd_name}."

        ok, updates, message = self.normalize_avd_config_inputs(
            ram_mb=ram_mb,
            heap_mb=heap_mb,
            data_partition=data_partition,
            show_device_frame=show_device_frame,
        )
        if not ok or updates is None:
            return False, message

        self.write_kv_file(
            config_path,
            updates,
        )
        self.runner.output_queue.put(f"[edit-avd] Configuración actualizada en {config_path}\n")
        return True, "Configuración actualizada."

    def list_avds(self, emulator_bin: str | None = None) -> tuple[int, list[str], str]:
        emulator_bin = (emulator_bin or self.derived_paths()["emulator"]).strip()
        code, output = self.runner.run_sync([emulator_bin, "-list-avds"], "list-avds")
        avds = [line.strip() for line in output.splitlines() if line.strip() and not line.startswith("[")]
        return code, avds, output

    def launch_emulator(
        self,
        avd_name: str,
        emulator_bin: str | None = None,
        wipe_data: bool = False,
        no_snapshot: bool = False,
        no_boot_anim: bool = False,
        verbose: bool = False,
    ) -> subprocess.Popen | None:
        emulator_bin = (emulator_bin or self.derived_paths()["emulator"]).strip()
        emulator_dir = str(Path(emulator_bin).resolve().parent)
        cmd = [emulator_bin, "-avd", avd_name]

        if wipe_data:
            cmd.append("-wipe-data")
        if no_snapshot:
            cmd.append("-no-snapshot")
        if no_boot_anim:
            cmd.append("-no-boot-anim")
        if verbose:
            cmd.append("-verbose")

        return self.runner.run_async(cmd, f"launch:{avd_name}", cwd=emulator_dir)

    def list_devices(self, avdmanager_bin: str | None = None) -> tuple[int, str]:
        avdmanager_bin = (avdmanager_bin or self.derived_paths()["avdmanager"]).strip()
        return self.runner.run_sync([avdmanager_bin, "list", "device"], "avdmanager-list-device")

    def list_available_devices(self, avdmanager_bin: str | None = None) -> tuple[int, list[DeviceInfo], str]:
        code, output = self.list_devices(avdmanager_bin=avdmanager_bin)
        devices: list[DeviceInfo] = []

        current_id: str | None = None
        current_name: str | None = None
        current_oem: str | None = None
        current_tag: str | None = None

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line.startswith("id: ") and 'or "' in line:
                if current_id and current_name:
                    devices.append(DeviceInfo(device_id=current_id, name=current_name, oem=current_oem, tag=current_tag))
                current_id = line.split('or "', 1)[1].split('"', 1)[0].strip()
                current_name = None
                current_oem = None
                current_tag = None
            elif line.startswith("Name:"):
                current_name = line.split(":", 1)[1].strip()
            elif line.startswith("OEM :"):
                current_oem = line.split(":", 1)[1].strip()
            elif line.startswith("Tag :"):
                current_tag = line.split(":", 1)[1].strip()

        if current_id and current_name:
            devices.append(DeviceInfo(device_id=current_id, name=current_name, oem=current_oem, tag=current_tag))

        return code, devices, output

    def list_images(self, sdkmanager_bin: str | None = None) -> tuple[int, str]:
        sdkmanager_bin = (sdkmanager_bin or self.derived_paths()["sdkmanager"]).strip()
        return self.runner.run_sync([sdkmanager_bin, "--list"], "sdkmanager-list")

    @staticmethod
    def _parse_system_image_line(line: str) -> tuple[str, str | None, str | None] | None:
        if not line:
            return None
        parts = [part.strip() for part in line.split("|")]
        package = parts[0] if parts else ""
        if not package.startswith("system-images;"):
            return None
        version = parts[1] if len(parts) > 1 and parts[1] else None
        description = parts[2] if len(parts) > 2 and parts[2] else None
        return package, version, description

    def list_system_image_catalog(self, sdkmanager_bin: str | None = None) -> tuple[int, list[ImagePackageInfo], str]:
        code, output = self.list_images(sdkmanager_bin=sdkmanager_bin)
        installed: dict[str, ImagePackageInfo] = {}
        available: dict[str, ImagePackageInfo] = {}
        updatable: set[str] = set()
        section = ""

        for raw_line in output.splitlines():
            line = raw_line.strip()
            lowered = line.lower()
            if lowered.startswith("installed packages:"):
                section = "installed"
                continue
            if lowered.startswith("available packages:"):
                section = "available"
                continue
            if lowered.startswith("available updates:"):
                section = "updates"
                continue
            if not line or lowered.startswith("path") or set(line) == {"-"}:
                continue

            parsed = self._parse_system_image_line(line)
            if not parsed:
                continue
            package, version, description = parsed
            if section == "installed":
                installed[package] = ImagePackageInfo(
                    package=package,
                    installed=True,
                    updatable=False,
                    version=version,
                    description=description,
                )
            elif section == "available":
                available[package] = ImagePackageInfo(
                    package=package,
                    installed=False,
                    updatable=False,
                    version=version,
                    description=description,
                )
            elif section == "updates":
                updatable.add(package)

        catalog: dict[str, ImagePackageInfo] = {}
        all_packages = set(installed) | set(available) | set(updatable)
        for package in all_packages:
            base = installed.get(package) or available.get(package)
            if base is None:
                base = ImagePackageInfo(package=package, installed=False)
            catalog[package] = ImagePackageInfo(
                package=package,
                installed=package in installed,
                updatable=package in updatable,
                version=base.version,
                description=base.description,
            )

        items = sorted(catalog.values(), key=lambda item: item.package)
        return code, items, output

    def list_available_images(self, sdkmanager_bin: str | None = None) -> tuple[int, list[str], str]:
        code, catalog, output = self.list_system_image_catalog(sdkmanager_bin=sdkmanager_bin)
        images = sorted(item.package for item in catalog if item.installed)
        return code, images, output

    def _run_sync_with_input(self, cmd: list[str], title: str, stdin_text: str | None = None) -> tuple[int, str]:
        try:
            self.runner.output_queue.put(f"\n[{title}] Ejecutando: {' '.join(cmd)}\n")
            proc = subprocess.Popen(
                cmd,
                env=self.runner.build_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                text=True,
                bufsize=1,
                shell=False,
            )

            if stdin_text is not None and proc.stdin:
                proc.stdin.write(stdin_text)
                proc.stdin.flush()
                proc.stdin.close()

            output_chunks: list[str] = []
            current_line = ""
            if proc.stdout:
                while True:
                    char = proc.stdout.read(1)
                    if char == "":
                        break
                    output_chunks.append(char)
                    if char in ("\n", "\r"):
                        if current_line:
                            self.runner.output_queue.put(current_line + "\n")
                            current_line = ""
                    else:
                        current_line += char
                if current_line:
                    self.runner.output_queue.put(current_line + "\n")
                proc.stdout.close()

            code = proc.wait()
            output = "".join(output_chunks)
            self.runner.output_queue.put(f"[{title}] exit={code}\n")
            return code, output
        except Exception as exc:
            msg = f"[{title}] error: {exc}\n"
            self.runner.output_queue.put(msg)
            return 1, msg

    def install_system_image(
        self,
        package: str,
        sdkmanager_bin: str | None = None,
        accept_licenses: bool = False,
    ) -> tuple[int, str]:
        sdkmanager_bin = (sdkmanager_bin or self.derived_paths()["sdkmanager"]).strip()
        stdin_text = ("y\n" * 256) if accept_licenses else None
        return self._run_sync_with_input([sdkmanager_bin, package], "sdkmanager-install-image", stdin_text=stdin_text)

    def update_system_image(
        self,
        package: str,
        sdkmanager_bin: str | None = None,
        accept_licenses: bool = False,
    ) -> tuple[int, str]:
        sdkmanager_bin = (sdkmanager_bin or self.derived_paths()["sdkmanager"]).strip()
        stdin_text = ("y\n" * 256) if accept_licenses else None
        return self._run_sync_with_input([sdkmanager_bin, package], "sdkmanager-update-image", stdin_text=stdin_text)

    def accept_licenses(self, sdkmanager_bin: str | None = None) -> tuple[int, str]:
        sdkmanager_bin = (sdkmanager_bin or self.derived_paths()["sdkmanager"]).strip()
        return self._run_sync_with_input([sdkmanager_bin, "--licenses"], "sdkmanager-licenses", stdin_text=("y\n" * 256))

    def create_avd(
        self,
        name: str,
        package: str,
        device: str,
        force: bool = False,
        avdmanager_bin: str | None = None,
        on_exit=None,
    ) -> subprocess.Popen | None:
        avdmanager_bin = (avdmanager_bin or self.derived_paths()["avdmanager"]).strip()
        cmd = [avdmanager_bin, "create", "avd", "-n", name, "-k", package, "-d", device]
        if force:
            cmd.append("-f")
        return self.runner.run_async(
            cmd,
            "create-avd",
            stdin_text="no\n",
            on_exit=on_exit,
        )

    def delete_avd(self, avd_name: str, avdmanager_bin: str | None = None) -> tuple[int, str]:
        avdmanager_bin = (avdmanager_bin or self.derived_paths()["avdmanager"]).strip()
        return self.runner.run_sync([avdmanager_bin, "delete", "avd", "-n", avd_name], f"delete-avd:{avd_name}")
