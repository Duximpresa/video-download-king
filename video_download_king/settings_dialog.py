from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import AppSettings
from .models import ProxyConfig


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(520, 300)

        tabs = QTabWidget()
        tabs.addTab(self._build_proxy_tab(settings), "代理")
        tabs.addTab(self._build_cookie_tab(settings), "YouTube 登录")
        tabs.addTab(self._build_douyin_cookie_tab(settings), "抖音登录")
        tabs.addTab(self._build_network_tab(settings), "网络")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _build_proxy_tab(self, settings: AppSettings) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.proxy_scheme = QComboBox()
        self.proxy_scheme.addItem("直连", "direct")
        for label, value in (
            ("HTTP", "http"),
            ("HTTPS", "https"),
            ("SOCKS4", "socks4"),
            ("SOCKS5", "socks5"),
        ):
            self.proxy_scheme.addItem(label, value)
        self.proxy_scheme.setCurrentIndex(max(0, self.proxy_scheme.findData(settings.proxy.scheme)))
        self.proxy_host = QLineEdit(settings.proxy.host)
        self.proxy_port = QSpinBox()
        self.proxy_port.setButtonSymbols(QSpinBox.NoButtons)
        self.proxy_port.setRange(0, 65535)
        self.proxy_port.setSpecialValueText("未设置")
        self.proxy_port.setValue(settings.proxy.port or 0)
        self.proxy_username = QLineEdit(settings.proxy.username)
        self.proxy_password = QLineEdit()
        self.proxy_password.setEchoMode(QLineEdit.Password)
        self.proxy_password.setPlaceholderText("仅本次运行使用，不写入配置")
        form.addRow("代理模式", self.proxy_scheme)
        form.addRow("主机", self.proxy_host)
        form.addRow("端口", self.proxy_port)
        form.addRow("用户名", self.proxy_username)
        form.addRow("密码", self.proxy_password)
        return page

    def _build_cookie_tab(self, settings: AppSettings) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.cookie_mode = QComboBox()
        self.cookie_mode.addItem("不使用", "")
        self.cookie_mode.addItem("Chrome 浏览器", "chrome")
        self.cookie_mode.addItem("Edge 浏览器", "edge")
        self.cookie_mode.setCurrentIndex(max(0, self.cookie_mode.findData(settings.cookie_browser)))
        self.cookie_file = QLineEdit(settings.cookie_file)
        browse = QPushButton("浏览...")
        browse.clicked.connect(self._browse_cookie)
        row = QHBoxLayout()
        row.addWidget(self.cookie_file)
        row.addWidget(browse)
        form.addRow("从浏览器读取", self.cookie_mode)
        form.addRow("或 cookies.txt", row)
        return page

    def _build_network_tab(self, settings: AppSettings) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.timeout = QSpinBox()
        self.timeout.setButtonSymbols(QSpinBox.NoButtons)
        self.timeout.setRange(5, 300)
        self.timeout.setSuffix(" 秒")
        self.timeout.setValue(settings.timeout)
        form.addRow("网络超时", self.timeout)
        return page

    def _build_douyin_cookie_tab(self, settings: AppSettings) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.douyin_cookie_file = QLineEdit(settings.douyin_cookie_file)
        browse = QPushButton("浏览...")
        browse.clicked.connect(self._browse_douyin_cookie)
        row = QHBoxLayout()
        row.addWidget(self.douyin_cookie_file)
        row.addWidget(browse)
        form.addRow("Netscape cookies.txt", row)
        return page

    def _browse_cookie(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 cookies.txt", "", "文本文件 (*.txt);;所有文件 (*)")
        if path:
            self.cookie_file.setText(path)

    def _browse_douyin_cookie(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择抖音 cookies.txt", "", "文本文件 (*.txt);;所有文件 (*)")
        if path:
            self.douyin_cookie_file.setText(path)

    def apply(self, settings: AppSettings) -> None:
        settings.proxy = ProxyConfig(
            scheme=self.proxy_scheme.currentData(),
            host=self.proxy_host.text().strip(),
            port=self.proxy_port.value() or None,
            username=self.proxy_username.text().strip(),
            password=self.proxy_password.text(),
        )
        settings.cookie_file = self.cookie_file.text().strip()
        settings.cookie_browser = self.cookie_mode.currentData()
        settings.douyin_cookie_file = self.douyin_cookie_file.text().strip()
        settings.timeout = self.timeout.value()
