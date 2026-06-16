from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QSpinBox, QVBoxLayout

from .models import TranscodeConfig


class TranscodePanel(QGroupBox):
    def __init__(self, title: str = "兼容 MP4", parent=None) -> None:
        super().__init__(title, parent)
        self.hardware_availability = {"nvidia": False, "intel": False, "amd": False}

        layout = QVBoxLayout(self)
        from PySide6.QtWidgets import QCheckBox

        self.transcode_check = QCheckBox("自动生成 H.264 + AAC 的 MP4")
        self.keep_source_check = QCheckBox("成功后保留原始下载文件")
        layout.addWidget(self.transcode_check)
        layout.addWidget(self.keep_source_check)

        form = QFormLayout()
        self.processor_combo = QComboBox()
        self.processor_combo.addItem("CPU", "cpu")
        self.processor_combo.addItem("GPU", "gpu")
        self.processor_combo.currentIndexChanged.connect(self._processor_changed)

        self.vendor_combo = QComboBox()
        self.vendor_combo.addItem("NVIDIA NVENC", "nvidia")
        self.vendor_combo.addItem("Intel QSV", "intel")
        self.vendor_combo.addItem("AMD AMF", "amd")

        self.rate_mode = QComboBox()
        self.rate_mode.addItem("自动", "auto")
        self.rate_mode.addItem("恒定质量", "quality")
        self.rate_mode.addItem("目标码率", "bitrate")
        self.rate_mode.currentIndexChanged.connect(self._rate_mode_changed)

        self.quality_spin = QSpinBox()
        self.quality_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.quality_spin.setRange(0, 51)
        self.quality_spin.setValue(23)

        self.video_bitrate = QSpinBox()
        self.video_bitrate.setButtonSymbols(QSpinBox.NoButtons)
        self.video_bitrate.setRange(0, 100000)
        self.video_bitrate.setSpecialValueText("自动")
        self.video_bitrate.setSuffix(" kbps")

        self.audio_bitrate = QComboBox()
        self.audio_bitrate.addItem("自动", 0)
        for value in (96, 128, 192, 256, 320):
            self.audio_bitrate.addItem(f"{value} kbps", value)

        self.audio_custom = QSpinBox()
        self.audio_custom.setButtonSymbols(QSpinBox.NoButtons)
        self.audio_custom.setRange(0, 512)
        self.audio_custom.setSpecialValueText("使用上方选项")
        self.audio_custom.setSuffix(" kbps")

        self.suffix_mode = QComboBox()
        self.suffix_mode.addItem("自动编码后缀", "auto")
        self.suffix_mode.addItem("自定义后缀", "custom")
        self.suffix_mode.addItem("不追加后缀", "none")
        self.suffix_mode.currentIndexChanged.connect(self._suffix_mode_changed)

        self.custom_suffix = QLineEdit()
        self.custom_suffix.setPlaceholderText("例如：_兼容版")

        form.addRow("转码处理器", self.processor_combo)
        form.addRow("GPU 厂商", self.vendor_combo)
        form.addRow("视频控制", self.rate_mode)
        form.addRow("质量值 (0-51)", self.quality_spin)
        form.addRow("视频码率", self.video_bitrate)
        form.addRow("音频码率", self.audio_bitrate)
        form.addRow("自定义音频码率", self.audio_custom)
        form.addRow("文件后缀", self.suffix_mode)
        form.addRow("自定义后缀", self.custom_suffix)
        layout.addLayout(form)

        note = QLabel("自动检测 NVIDIA NVENC、Intel QSV、AMD AMF；实际转码失败时询问是否回退 CPU。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#687386")
        layout.addWidget(note)
        layout.addStretch()

        self._rate_mode_changed()
        self._suffix_mode_changed()
        self._processor_changed()

    def load_config(self, config: TranscodeConfig) -> None:
        self.transcode_check.setChecked(config.enabled)
        self.keep_source_check.setChecked(config.keep_source)
        self.rate_mode.setCurrentIndex(max(0, self.rate_mode.findData(config.rate_mode)))
        self.quality_spin.setValue(config.quality)
        self.video_bitrate.setValue(config.video_bitrate_kbps or 0)
        audio_index = self.audio_bitrate.findData(config.audio_bitrate_kbps or 0)
        self.audio_bitrate.setCurrentIndex(max(0, audio_index))
        self.audio_custom.setValue(0 if audio_index >= 0 else config.audio_bitrate_kbps or 0)
        self.processor_combo.setCurrentIndex(max(0, self.processor_combo.findData(config.processor)))
        self.vendor_combo.setCurrentIndex(max(0, self.vendor_combo.findData(config.hardware_vendor)))
        self.suffix_mode.setCurrentIndex(max(0, self.suffix_mode.findData(config.suffix_mode)))
        self.custom_suffix.setText(config.custom_suffix)
        self._processor_changed()
        self._suffix_mode_changed()

    def to_config(
        self,
        *,
        enabled: bool | None = None,
        source_video_bitrate_kbps: int | None = None,
        source_video_codec: str = "",
    ) -> TranscodeConfig:
        audio_rate = self.audio_custom.value() or self.audio_bitrate.currentData() or None
        return TranscodeConfig(
            enabled=self.transcode_check.isChecked() if enabled is None else enabled,
            keep_source=self.keep_source_check.isChecked(),
            processor=self.processor_combo.currentData(),
            hardware_vendor=self.vendor_combo.currentData(),
            rate_mode=self.rate_mode.currentData(),
            quality=self.quality_spin.value(),
            video_bitrate_kbps=self.video_bitrate.value() or None,
            audio_bitrate_kbps=audio_rate,
            source_video_bitrate_kbps=source_video_bitrate_kbps,
            source_video_codec=source_video_codec,
            suffix_mode=self.suffix_mode.currentData(),
            custom_suffix=self.custom_suffix.text(),
        )

    def set_available_hardware(self, availability: dict[str, bool]) -> None:
        self.hardware_availability = availability
        labels = {
            "nvidia": "NVIDIA NVENC",
            "intel": "Intel QSV",
            "amd": "AMD AMF",
        }
        for index in range(self.vendor_combo.count()):
            vendor = self.vendor_combo.itemData(index)
            item = self.vendor_combo.model().item(index)
            available = self.hardware_availability.get(vendor, False)
            item.setEnabled(available)
            self.vendor_combo.setItemText(index, labels[vendor] + ("" if available else "（不可用）"))
        if self.processor_combo.currentData() == "gpu" and not self.hardware_availability.get(
            self.vendor_combo.currentData(), False
        ):
            self.processor_combo.setCurrentIndex(self.processor_combo.findData("cpu"))
        self._processor_changed()

    def set_transcode_allowed(self, allowed: bool) -> None:
        self.transcode_check.setEnabled(allowed)

    def _rate_mode_changed(self) -> None:
        mode = self.rate_mode.currentData()
        self.quality_spin.setEnabled(mode == "quality")
        self.video_bitrate.setEnabled(mode == "bitrate")

    def _processor_changed(self) -> None:
        gpu = self.processor_combo.currentData() == "gpu"
        self.vendor_combo.setEnabled(gpu)
        if gpu and not self.hardware_availability.get(self.vendor_combo.currentData(), False):
            first_available = next((vendor for vendor, available in self.hardware_availability.items() if available), None)
            if first_available:
                self.vendor_combo.setCurrentIndex(self.vendor_combo.findData(first_available))

    def _suffix_mode_changed(self) -> None:
        self.custom_suffix.setEnabled(self.suffix_mode.currentData() == "custom")
