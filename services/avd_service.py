from __future__ import annotations

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


@dataclass
class DeviceInfo:
    device_id: str
    name: str
    oem: str | None = None
    tag: str | None = None


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
        }

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
        info = [AvdInfo(name=avd, status=self.avd_status(avd), config_path=self.avd_config_path(avd)) for avd in avds]
        return code, info, output

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

        if not ram_mb.isdigit() or not heap_mb.isdigit():
            return False, "RAM y VM Heap deben ser enteros."
        if not re.fullmatch(r"\d+[MG]", data_partition, re.IGNORECASE):
            return False, "Data partition debe verse como 2G o 512M."

        frame = show_device_frame.strip().lower()
        if frame not in {"yes", "no"}:
            return False, "Show device frame debe ser yes o no."

        self.write_kv_file(
            config_path,
            {
                "hw.ramSize": ram_mb.strip(),
                "vm.heapSize": heap_mb.strip(),
                "disk.dataPartition.size": data_partition.strip().upper(),
                "showDeviceFrame": frame,
            },
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

    def list_available_images(self, sdkmanager_bin: str | None = None) -> tuple[int, list[str], str]:
        code, output = self.list_images(sdkmanager_bin=sdkmanager_bin)
        images: list[str] = []
        seen: set[str] = set()

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line.startswith("system-images;"):
                continue

            package = line.split("|", 1)[0].strip()
            if package and package not in seen:
                images.append(package)
                seen.add(package)

        images.sort()
        return code, images, output

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
