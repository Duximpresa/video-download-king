from __future__ import annotations

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import AppSettings
from .models import ProxyConfig
from .network_test import NetworkTestWorker


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(560, 390)
        self.network_test_thread: QThread | None = None
        self.network_test_worker: NetworkTestWorker | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_proxy_tab(settings), "代理")
        tabs.addTab(self._build_cookie_tab(settings), "YouTube / Instagram / TikTok / X 登录")
        tabs.addTab(self._build_douyin_cookie_tab(settings), "抖音登录")
        tabs.addTab(self._build_bilibili_cookie_tab(settings), "B站登录")
        tabs.addTab(self._build_xiaohongshu_cookie_tab(settings), "小红书登录")
        tabs.addTab(self._build_network_tab(settings), "网络")

        self.dialog_buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.dialog_buttons.button(QDialogButtonBox.Save).setText("保存")
        self.dialog_buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.dialog_buttons.accepted.connect(self.accept)
        self.dialog_buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(self.dialog_buttons)

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
        self.test_url = QLineEdit("https://www.google.com/")
        self.test_url.setPlaceholderText("https://www.google.com/")
        self.test_button = QPushButton("测试网络连通性")
        self.test_button.clicked.connect(self._start_network_test)
        self.test_progress = QProgressBar()
        self.test_progress.setRange(0, 100)
        self.test_progress.setValue(0)
        self.test_progress.setTextVisible(False)
        self.test_progress.setFixedHeight(8)
        self.test_result = QLabel("使用当前页面中的代理设置进行测试，无需先保存。")
        self.test_result.setWordWrap(True)
        test_controls = QHBoxLayout()
        test_controls.addWidget(self.test_url, 1)
        test_controls.addWidget(self.test_button)
        form.addRow("测试网址", test_controls)
        form.addRow("", self.test_progress)
        form.addRow("测试结果", self.test_result)
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
        self.clear_cookie_button = QPushButton("清除")
        self.clear_cookie_button.clicked.connect(self.cookie_file.clear)
        row = QHBoxLayout()
        row.addWidget(self.cookie_file)
        row.addWidget(browse)
        row.addWidget(self.clear_cookie_button)
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
        self.clear_douyin_cookie_button = QPushButton("清除")
        self.clear_douyin_cookie_button.clicked.connect(self.douyin_cookie_file.clear)
        row = QHBoxLayout()
        row.addWidget(self.douyin_cookie_file)
        row.addWidget(browse)
        row.addWidget(self.clear_douyin_cookie_button)
        form.addRow("Netscape cookies.txt", row)
        hint = QLabel("未设置时会使用 YouTube / Instagram / TikTok / X 页的通用 cookies.txt；已填写但文件无效时会直接报错。")
        hint.setWordWrap(True)
        form.addRow("说明", hint)
        return page

    def _build_bilibili_cookie_tab(self, settings: AppSettings) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.bilibili_cookie_file = QLineEdit(settings.bilibili_cookie_file)
        browse = QPushButton("浏览...")
        browse.clicked.connect(self._browse_bilibili_cookie)
        self.clear_bilibili_cookie_button = QPushButton("清除")
        self.clear_bilibili_cookie_button.clicked.connect(self.bilibili_cookie_file.clear)
        row = QHBoxLayout()
        row.addWidget(self.bilibili_cookie_file)
        row.addWidget(browse)
        row.addWidget(self.clear_bilibili_cookie_button)
        form.addRow("Netscape cookies.txt", row)
        hint = QLabel("仅用于自研 B站引擎。未设置时会使用 YouTube / Instagram / TikTok / X 页的通用 cookies.txt；会员或受限画质取决于账号的正常播放权限。")
        hint.setWordWrap(True)
        form.addRow("说明", hint)
        return page

    def _build_xiaohongshu_cookie_tab(self, settings: AppSettings) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.xiaohongshu_cookie_file = QLineEdit(settings.xiaohongshu_cookie_file)
        browse = QPushButton("浏览...")
        browse.clicked.connect(self._browse_xiaohongshu_cookie)
        self.clear_xiaohongshu_cookie_button = QPushButton("清除")
        self.clear_xiaohongshu_cookie_button.clicked.connect(self.xiaohongshu_cookie_file.clear)
        row = QHBoxLayout()
        row.addWidget(self.xiaohongshu_cookie_file)
        row.addWidget(browse)
        row.addWidget(self.clear_xiaohongshu_cookie_button)
        form.addRow("Netscape cookies.txt", row)
        hint = QLabel("仅用于自研小红书引擎；未设置时会使用 YouTube / Instagram / TikTok / X 页的通用 cookies.txt。遇到登录限制或安全验证时，请导出最新的小红书网站 Cookie。")
        hint.setWordWrap(True)
        form.addRow("说明", hint)
        return page

    def _browse_cookie(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 cookies.txt", "", "文本文件 (*.txt);;所有文件 (*)")
        if path:
            self.cookie_file.setText(path)

    def _browse_douyin_cookie(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择抖音 cookies.txt", "", "文本文件 (*.txt);;所有文件 (*)")
        if path:
            self.douyin_cookie_file.setText(path)

    def _browse_bilibili_cookie(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 B站 cookies.txt", "", "文本文件 (*.txt);;所有文件 (*)")
        if path:
            self.bilibili_cookie_file.setText(path)

    def _browse_xiaohongshu_cookie(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择小红书 cookies.txt", "", "文本文件 (*.txt);;所有文件 (*)")
        if path:
            self.xiaohongshu_cookie_file.setText(path)

    def _proxy_from_form(self) -> ProxyConfig:
        return ProxyConfig(
            scheme=self.proxy_scheme.currentData(),
            host=self.proxy_host.text().strip(),
            port=self.proxy_port.value() or None,
            username=self.proxy_username.text().strip(),
            password=self.proxy_password.text(),
        )

    def _start_network_test(self) -> None:
        if self.network_test_thread:
            return
        try:
            proxy = self._proxy_from_form()
            proxy.url()
        except ValueError as exc:
            self.test_result.setText(f"连接失败：{exc}")
            self.test_result.setStyleSheet("color:#dc2626")
            return
        self.test_button.setEnabled(False)
        self.test_button.setText("测试中...")
        self.dialog_buttons.setEnabled(False)
        self.test_result.setText("正在连接目标网站...")
        self.test_result.setStyleSheet("color:#475569")
        self.test_progress.setRange(0, 0)
        thread = QThread(self)
        worker = NetworkTestWorker(self.test_url.text(), proxy, self.timeout.value())
        self.network_test_thread = thread
        self.network_test_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._network_test_complete)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._network_test_finished)
        thread.start()

    def _network_test_complete(self, success: bool, message: str) -> None:
        self.test_result.setText(message)
        self.test_result.setStyleSheet("color:#16803c" if success else "color:#dc2626")

    def _network_test_finished(self) -> None:
        self.network_test_thread = None
        self.network_test_worker = None
        self.test_button.setEnabled(True)
        self.test_button.setText("测试网络连通性")
        self.dialog_buttons.setEnabled(True)
        self.test_progress.setRange(0, 100)
        self.test_progress.setValue(100)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.network_test_thread:
            event.ignore()
            return
        super().closeEvent(event)

    def apply(self, settings: AppSettings) -> None:
        settings.proxy = self._proxy_from_form()
        settings.cookie_file = self.cookie_file.text().strip()
        settings.cookie_browser = self.cookie_mode.currentData()
        settings.douyin_cookie_file = self.douyin_cookie_file.text().strip()
        settings.xiaohongshu_cookie_file = self.xiaohongshu_cookie_file.text().strip()
        settings.bilibili_cookie_file = self.bilibili_cookie_file.text().strip()
        settings.timeout = self.timeout.value()
