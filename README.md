# PyAndroidEmuManager

Administrador gráfico de Android Virtual Devices (AVD) construido en Python usando Tkinter.

Permite:

- detectar Android SDK automáticamente
- listar AVDs disponibles
- lanzar emuladores Android
- visualizar logs en tiempo real
- crear nuevos AVDs usando `avdmanager`
- trabajar en macOS, Linux y Windows

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
- Tkinter funcional
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

## Instalar dependencias

```bash
pip install pyinstaller
```

---

# Compilar aplicación

```bash
pyinstaller --clean --windowed --icon app.icns --name "Py Android Emu Manager" py-avd.py
```

---

# Resultado

```text
dist/Py Android Emu Manager.app
```

---

# Recomendación para compartir entre devs

Firmar localmente la app usando ad-hoc signing:

```bash
codesign --force --deep --sign - \
  "dist/Py Android Emu Manager.app"
```

Luego comprimir:

```bash
ditto -c -k --keepParent \
  "dist/Py Android Emu Manager.app" \
  "PyAndroidEmuManager.zip"
```

---

# macOS: abrir app no notarizada

Esta app no está notarizada por Apple.

Si macOS bloquea la apertura, ejecutar:

```bash
xattr -dr com.apple.quarantine "Py Android Emu Manager.app"
```

Luego abrir:

```bash
open "Py Android Emu Manager.app"
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

## Instalar PyInstaller

```bash
pip install pyinstaller
```

## Compilar

```bash
pyinstaller --clean --windowed --name "Py Android Emu Manager" py-avd.py
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

## Instalar PyInstaller

```bash
pip install pyinstaller
```

## Compilar

```bash
pyinstaller --clean --windowed --name "Py Android Emu Manager" py-avd.py
```

---

# Nota importante

La aplicación debe compilarse en el sistema operativo de destino.

Ejemplo:

- macOS → compilar en macOS
- Linux → compilar en Linux
- Windows → compilar en Windows

PyInstaller no realiza cross-compilation entre plataformas.

---

# Dependencias Python

Actualmente el proyecto utiliza únicamente librerías estándar de Python:

- tkinter
- subprocess
- pathlib
- threading
- queue
- platform
- os

Dependencia externa requerida:

```text
pyinstaller
```
