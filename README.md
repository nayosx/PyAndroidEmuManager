# PyAndroidEmuManager

Administrador gráfico de Android Virtual Devices (AVD) construido en Python.

Permite:

- detectar Android SDK automáticamente
- listar AVDs disponibles
- lanzar emuladores Android
- visualizar logs en tiempo real
- crear nuevos AVDs usando `avdmanager`
- trabajar en macOS, Linux y Windows

---

# Versiones disponibles

El proyecto cuenta con dos aplicaciones que comparten el mismo código base de servicios y lógica:

| Versión | Archivo | Framework UI | Descripción |
|---------|---------|--------------|-------------|
| Tkinter | `py-avd.py` | Tkinter | Interfaz nativa del sistema operativo |
| Flet | `flet_avd.py` | Flet | Interfaz moderna estilo web |

Ambas versiones ofrecen la misma funcionalidad. La lógica compartida se encuentra en:

- `services/` — detección de SDK, manejo de AVDs
- `widgets/` — componentes de UI reutilizables (versión Flet)
- `dialogs/` — diálogos de la aplicación (versión Flet)

---

# Compilar en macOS

## Requerimientos

### Sistema

- macOS
- Xcode Command Line Tools

Verificar:

```bash
xcode-select -p
```

Si no están instaladas:

```bash
xcode-select --install
```

---

### Android

- Android Studio
- Android SDK
- Android Emulator
- AVD instalados
- mínimo 1 AVD configurado

---

### Python

- Python 3.x
- Tkinter funcional (versión Tkinter)
- entorno virtual recomendado

Verificar Tkinter:

```bash
python3 -m tkinter
```

Debe abrir una ventana pequeña.

---

# Preparar entorno

## Crear entorno virtual

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

# Compilar versión Tkinter (`py-avd.py`)

## Instalar dependencia

```bash
pip install pyinstaller
```

## Compilar

```bash
pyinstaller --clean --windowed --icon app.icns --name "Android Emu Manager" py-avd.py
```

## Resultado

```text
dist/Android Emu Manager.app
```

---

# Compilar versión Flet (`flet_avd.py`)

## Instalar dependencias

```bash
pip install flet
```

## Compilar

```bash
flet pack flet_avd.py \
  --name "Android Emu Manager Flet" \
  --icon android.icns \
  --add-data "mobile.png:."
```

> `--add-data "mobile.png:."` incluye la imagen usada en la UI dentro del bundle.

## Resultado

```text
dist/Android Emu Manager Flet.app
```

---

# Recomendación para compartir entre devs

Firmar localmente la app usando ad-hoc signing:

```bash
codesign --force --deep --sign - \
  "dist/Android Emu Manager Flet.app"
```

Luego comprimir:

```bash
ditto -c -k --keepParent \
  "dist/Android Emu Manager Flet.app" \
  "PyAndroidEmuManagerFlet.zip"
```

---

# macOS: abrir app no notarizada

Esta app no está notarizada por Apple.

Si macOS bloquea la apertura, ejecutar:

```bash
xattr -dr com.apple.quarantine "dist/Android Emu Manager Flet.app"
```

Luego abrir:

```bash
open "dist/Android Emu Manager Flet.app"
```

---

# Compilar en Linux

## Requerimientos

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
```

## Crear entorno

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Versión Tkinter

```bash
pip install pyinstaller
pyinstaller --clean --windowed --name "Android Emu Manager" py-avd.py
```

## Versión Flet

```bash
pip install flet
flet pack flet_avd.py \
  --name "Android Emu Manager Flet" \
  --icon android.icns \
  --add-data "mobile.png:."
```

---

# Compilar en Windows

## Requerimientos

- Python 3
- Tkinter funcional

Verificar:

```bash
py -m tkinter
```

## Crear entorno

```bash
py -m venv .venv
.venv\Scripts\activate
```

## Versión Tkinter

```bash
pip install pyinstaller
pyinstaller --clean --windowed --name "Android Emu Manager" py-avd.py
```

## Versión Flet

```bash
pip install flet
flet pack flet_avd.py \
  --name "Android Emu Manager Flet" \
  --icon android.icns \
  --add-data "mobile.png:."
```

---

# Nota importante

Cada versión debe compilarse en el sistema operativo de destino.

Ejemplo:

- macOS → compilar en macOS
- Linux → compilar en Linux
- Windows → compilar en Windows

PyInstaller y Flet no realizan cross-compilation entre plataformas.

---

# Dependencias Python

## Versión Tkinter (`py-avd.py`)

Utiliza únicamente librerías estándar:

- tkinter
- subprocess
- pathlib
- threading
- queue
- platform
- os

Dependencia externa:

```text
pyinstaller
```

## Versión Flet (`flet_avd.py`)

Dependencias externas:

```text
flet
```
