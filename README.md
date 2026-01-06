# 📲 Termux-Shizuku Web server on python

A high-performance Python-based web server running inside **Termux** that allows for remote file management and **seamless APK installation** via the **Shizuku** bridge.

## ⚡ The Problem vs. Our Solution

Standard file managers and Termux servers often fail to install APKs on Android 13/14+ due to strict **SELinux policies** and `Permission Denied` errors when accessing `/sdcard/`.

**This project solves it by:**

1. **Shizuku Integration:** Utilizing `rish` to communicate with the Shizuku server.
2. **Elevated Execution:** Moving APKs to `/data/local/tmp/` (the same folder used by `adb install`) before execution.
3. **Streamed Installation:** Using the `pm install -S` command to bypass file system permission bottlenecks.

## ✨ Core Features

* **Wireless APK Installer:** Upload and install apps on your phone from any PC on the same network.
* **Quiet Mode:** Background installation without annoying "Open with..." system pop-ups.
* **Modern File Manager:** Full web UI with a custom-built context menu.
* **Mobile-Friendly:** Long-press support on touchscreens to trigger file actions (Download, Delete, Install).
* **Dark Mode UI:** Optimized for developers and terminal lovers.

## 🛠️ Requirements

* **Android 11+** (for Shizuku wireless debugging support).
* **Termux** (installed from F-Droid).
* **Shizuku App** (running and authorized for Termux).

## 🚀 Quick Start

1. **Prepare Environment:**
```bash
pkg update && pkg upgrade
pkg install python
pip install flask

```


2. **Authorize Shizuku:**
Ensure you have run the Shizuku setup and authorized Termux in the Shizuku app.
3. **Run the Server:**
```bash
python server9.py

```


4. **Access Web UI:**
Open `http://your-phone-ip:5000` in your browser.

## 🖥️ Custom Context Menu

The script features a native-like context menu for both desktop and mobile:

* **PC:** Right-click to manage files.
* **Mobile:** Long-press to open actions.

## 📜 License

MIT – Free to use, modify, and distribute.
