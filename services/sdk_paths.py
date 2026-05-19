from __future__ import annotations

import os
import platform
from pathlib import Path


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
            candidates = [home / "Library" / "Android" / "sdk"]
        elif system == "Linux":
            candidates = [home / "Android" / "Sdk", home / "Android" / "sdk"]
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
