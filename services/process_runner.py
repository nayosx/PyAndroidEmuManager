from __future__ import annotations

import os
import platform
import queue
import subprocess
import threading
from collections.abc import Callable

from services.sdk_paths import AndroidSdkPaths


class StreamReader(threading.Thread):
    def __init__(self, pipe, output_queue: queue.Queue[str], prefix: str = ""):
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


class ProcessRunner:
    def __init__(self, sdk_root: str, output_queue: queue.Queue[str]):
        self.sdk_root = sdk_root
        self.output_queue = output_queue

    def set_sdk_root(self, sdk_root: str) -> None:
        self.sdk_root = sdk_root

    def build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        sdk_root = self.sdk_root.strip()
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

    def run_sync(self, cmd: list[str], title: str) -> tuple[int, str]:
        try:
            self.output_queue.put(f"\n[{title}] Ejecutando: {' '.join(cmd)}\n")
            proc = subprocess.run(
                cmd,
                env=self.build_env(),
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            if output:
                self.output_queue.put(output + ("" if output.endswith("\n") else "\n"))
            self.output_queue.put(f"[{title}] exit={proc.returncode}\n")
            return proc.returncode, output
        except Exception as exc:
            msg = f"[{title}] error: {exc}\n"
            self.output_queue.put(msg)
            return 1, msg

    def run_async(
        self,
        cmd: list[str],
        title: str,
        cwd: str | None = None,
        stdin_text: str | None = None,
        on_exit: Callable[[int], None] | None = None,
    ) -> subprocess.Popen | None:
        try:
            self.output_queue.put(f"\n[{title}] Ejecutando: {' '.join(cmd)}\n")
            if cwd:
                self.output_queue.put(f"[{title}] cwd={cwd}\n")

            creationflags = 0
            if platform.system() == "Windows":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                cmd,
                env=self.build_env(),
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                text=True,
                bufsize=1,
                shell=False,
                creationflags=creationflags,
            )

            if stdin_text is not None and proc.stdin:
                proc.stdin.write(stdin_text)
                proc.stdin.flush()
                proc.stdin.close()

            if proc.stdout:
                StreamReader(proc.stdout, self.output_queue).start()

            def waiter() -> None:
                code = proc.wait()
                self.output_queue.put(f"[{title}] exit={code}\n")
                if on_exit:
                    on_exit(code)

            threading.Thread(target=waiter, daemon=True).start()
            return proc
        except Exception as exc:
            self.output_queue.put(f"[{title}] error: {exc}\n")
            return None
