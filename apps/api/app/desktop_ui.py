"""A small native companion. Qt is an optional dependency of the local API."""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .desktop_runtime import (
    LocalGateway, configure_desktop, data_directory, export_extension,
    extension_source, saved_provider,
)


class CompanionWindow(QMainWindow):
    def __init__(self, directory, preferences, *, autostart=True):
        super().__init__()
        self.directory = directory
        self.preferences = preferences
        self.gateway = None
        self.closing = False
        self.pair_expires = 0
        self.last_state = None
        self.setWindowTitle("Manga Thai Reader")
        self.resize(640, 620)
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = QLabel("Manga Thai Reader")
        title.setStyleSheet("font-size: 25px; font-weight: 600")
        layout.addWidget(title)
        layout.addWidget(QLabel("เปิดหน้าต่างนี้ไว้ระหว่างอ่าน · ปิดหน้าต่างเพื่อหยุดระบบแปล"))
        self.status = QLabel("กำลังเปิดระบบแปล…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        mode_row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("ทดลองใช้งาน · ข้อความตัวอย่าง ไม่อ่านภาพจริง", "mock")
        self.mode.addItem("ใช้ ChatGPT · ต้องเชื่อมต่อบัญชีและอาจใช้โควตา", "chatgpt_oauth")
        self.mode.setCurrentIndex(1 if saved_provider(preferences) == "chatgpt_oauth" else 0)
        mode_row.addWidget(self.mode, 1)
        self.toggle = QPushButton("เริ่มระบบแปล")
        self.toggle.clicked.connect(self.toggle_gateway)
        mode_row.addWidget(self.toggle)
        layout.addLayout(mode_row)
        layout.addWidget(QLabel("ตั้งค่าครั้งแรก"))
        self.install = QPushButton("1. เปิดโฟลเดอร์ extension")
        self.install.clicked.connect(self.open_extension)
        layout.addWidget(self.install)
        self.instructions = QLabel(
            "ใน Chrome เปิด chrome://extensions → เปิด Developer mode → Load unpacked\n"
            "เลือกโฟลเดอร์ extension ที่แอปเปิดให้ แล้วเปิด Options ของส่วนขยาย"
        )
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)
        pair_row = QHBoxLayout()
        self.pair = QPushButton("2. สร้างรหัสจับคู่")
        self.pair.clicked.connect(self.create_pairing)
        pair_row.addWidget(self.pair)
        self.code = QLineEdit()
        self.code.setReadOnly(True)
        self.code.setPlaceholderText("รหัสใช้ได้ครั้งเดียวภายใน 10 นาที")
        pair_row.addWidget(self.code, 1)
        self.copy = QPushButton("คัดลอกรหัส")
        self.copy.clicked.connect(self.copy_pairing)
        pair_row.addWidget(self.copy)
        layout.addLayout(pair_row)
        self.pair_help = QLabel("นำรหัสไปกรอกใน Options และยืนยันสิทธิ์ · ไม่ต้องจับคู่ซ้ำทุกครั้ง")
        self.pair_help.setWordWrap(True)
        layout.addWidget(self.pair_help)
        connection = QLabel(
            "3. เลือกโหมดใช้ ChatGPT แล้วเริ่มระบบแปลใหม่ จาก Options กด “จัดการการเชื่อมต่อ”\n"
            "เข้าสู่ระบบบัญชีของคุณ อนุญาตการใช้งาน และเลือกโมเดลที่รองรับภาพ\n\n"
            "เมื่อพร้อมแล้ว เปิดแท็บมังงะ กดไอคอนส่วนขยาย แล้วกด “แปลภาพที่เห็น”"
        )
        connection.setWordWrap(True)
        layout.addWidget(connection)
        layout.addStretch()
        privacy = QLabel("บัญชีเก็บเฉพาะในเครื่องนี้ · รูปที่สั่งแปลจะส่งไปยังผู้ให้บริการในโหมด ChatGPT")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(150)
        self.refresh()
        if autostart:
            self.start_gateway()

    def start_gateway(self):
        provider = self.mode.currentData()
        try:
            self.preferences._write("desktop.json", {"provider": provider})
        except (OSError, RuntimeError):
            self.status.setText("บันทึกการตั้งค่าไม่ได้ ตรวจสิทธิ์โฟลเดอร์ข้อมูลแล้วลองอีกครั้ง")
            return
        self.gateway = LocalGateway(provider)
        self.gateway.start()
        self.refresh()

    def toggle_gateway(self):
        if self.gateway and self.gateway.state in {"running", "starting"}:
            self.gateway.request_stop()
        else:
            self.start_gateway()
        self.refresh()

    def refresh(self):
        state = self.gateway.state if self.gateway else "stopped"
        active = state in {"starting", "running", "stopping"}
        self.mode.setEnabled(not active and not self.closing)
        self.toggle.setEnabled(state not in {"starting", "stopping"} and not self.closing)
        self.toggle.setText("หยุดระบบแปล" if active else "เริ่มระบบแปล")
        self.pair.setEnabled(state == "running" and not self.closing)
        if self.pair_expires and (time.monotonic() >= self.pair_expires or state != "running"):
            self.code.clear()
            self.pair_expires = 0
        self.copy.setEnabled(bool(self.code.text()) and state == "running")
        if state != self.last_state:
            messages = {
                "starting": "กำลังเปิดระบบแปล…",
                "running": "พร้อมใช้งาน · " + ("โหมดทดลอง ข้อความตัวอย่าง" if self.mode.currentData() == "mock" else "โหมด ChatGPT"),
                "stopping": "กำลังหยุดระบบแปล…",
                "stopped": "ระบบแปลหยุดอยู่ เลือกโหมดแล้วกดเริ่มได้เลย",
                "failed": ("เปิดระบบแปลไม่ได้ พอร์ตถูกใช้หรือเข้าไม่ได้ ปิดแอปที่เปิดซ้ำหรือระบบ Docker เดิม แล้วลองใหม่"
                           if self.gateway and self.gateway.error == "port_unavailable"
                           else "เปิดระบบแปลไม่สำเร็จ ลองปิดแล้วเปิดแอปใหม่"),
            }
            self.status.setText(messages[state])
            self.last_state = state
        if self.closing and state not in {"starting", "running", "stopping"}:
            self.close()

    def create_pairing(self):
        if not self.gateway or self.gateway.state != "running":
            return
        if self.code.text() and not QMessageBox.question(
            self, "สร้างรหัสใหม่", "รหัสที่แสดงอยู่จะใช้ไม่ได้ ต้องการสร้างรหัสใหม่หรือไม่?"
        ) == QMessageBox.StandardButton.Yes:
            return
        try:
            self.code.setText(self.gateway.issue_pairing())
            self.pair_expires = time.monotonic() + 600
            self.pair_help.setText("คัดลอกรหัสไปกรอกใน Options · เมื่อจับคู่สำเร็จจะให้สิทธิ์ส่วนขยายนี้แทนส่วนขยายเดิม")
        except (OSError, RuntimeError):
            self.pair_help.setText("สร้างรหัสไม่ได้ ตรวจสิทธิ์โฟลเดอร์ข้อมูลแล้วลองอีกครั้ง")
        self.refresh()

    def copy_pairing(self):
        self.refresh()
        if self.copy.isEnabled():
            QApplication.clipboard().setText(self.code.text())

    def open_extension(self):
        try:
            destination = export_extension(extension_source(), self.directory / "extension")
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination)))
            if not opened:
                raise OSError("File manager unavailable")
        except (OSError, RuntimeError):
            self.instructions.setText("เปิดโฟลเดอร์ extension ไม่ได้ ตรวจสิทธิ์โฟลเดอร์ข้อมูลแล้วลองอีกครั้ง")

    def closeEvent(self, event):
        if self.gateway and self.gateway.state in {"starting", "running", "stopping"}:
            self.closing = True
            self.gateway.request_stop()
            event.ignore()
            self.refresh()
            return
        self.timer.stop()
        event.accept()


def main():
    application = QApplication(sys.argv[:1])
    application.setApplicationName("Manga Thai Reader")
    directory = data_directory()
    try:
        preferences = configure_desktop(directory)
    except (OSError, RuntimeError):
        QMessageBox.critical(None, "Manga Thai Reader", "เปิดโฟลเดอร์ข้อมูลไม่ได้ ตรวจสิทธิ์ของบัญชีผู้ใช้แล้วลองใหม่")
        return 1
    window = CompanionWindow(directory, preferences)
    window.show()
    return application.exec()
