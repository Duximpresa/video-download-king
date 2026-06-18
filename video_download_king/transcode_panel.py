from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .models import TranscodeConfig
from .transcode_options import (
    AUDIO_BITRATE_PRESETS,
    MAX_BITRATE_PRESETS,
    SCALE_PRESETS,
    VIDEO_BITRATE_PRESETS,
    bitrate_for_target_size,
    clamp_audio_bitrate,
    estimate_size_mib,
    portrait_expression,
    resolve_scale,
    resolve_video_bitrate,
)


def _editable_combo(values, *, numeric: bool = False) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setMaxVisibleItems(24)
    for value in values:
        combo.addItem(str(value), value)
    if numeric:
        combo.lineEdit().setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{1,6}")))
    return combo


class TranscodePanel(QGroupBox):
    def __init__(self, title: str = "视频编码", parent=None, *, compact: bool = False) -> None:
        super().__init__(title, parent)
        self.compact = compact
        self.hardware_availability: dict[str, bool] = {
            "nvidia": False,
            "intel": False,
            "amd": False,
        }
        self._media_width = 1920
        self._media_height = 1080
        self._media_fps = 25.0
        self._media_duration: float | None = None
        self._updating = False

        self.transcode_check = QCheckBox("启用 H.264 MP4 视频编码")
        self.keep_source_check = QCheckBox("成功后保留原始下载文件")

        self.scale_combo = _editable_combo(SCALE_PRESETS)
        self.scale_combo.setCurrentText("源尺寸")
        self.scale_combo.lineEdit().setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"(源尺寸|1:\d+|\d+[xX×]\d+|(?:auto|\d+):(?:auto|\d+))")
            )
        )
        self.portrait_check = QCheckBox("竖构图")
        self.portrait_check.toggled.connect(self._portrait_changed)
        self.rotation_combo = QComboBox()
        for label, value in (("不旋转", "0"), ("顺时针 90°", "90"), ("逆时针 90°", "-90"), ("180°", "180")):
            self.rotation_combo.addItem(label, value)
        self.mirror_check = QCheckBox("水平镜像")
        self.force_dar_check = QCheckBox("强制显示比例")
        self.no_upscale_check = QCheckBox("禁止放大")
        self.scale_algorithm = QComboBox()
        for label, value in (
            ("Lanczos（清晰）", "lanczos"),
            ("Bicubic（平衡）", "bicubic"),
            ("Bilinear（快速）", "bilinear"),
            ("Nearest（像素）", "neighbor"),
        ):
            self.scale_algorithm.addItem(label, value)

        self.rate_mode = QComboBox()
        self.rate_mode.addItem("VBR", "vbr")
        self.rate_mode.addItem("CBR", "cbr")
        self.rate_mode.addItem("CQ", "cq")
        self.rate_mode.currentIndexChanged.connect(self._rate_mode_changed)
        self.video_bitrate_label = QLabel("视频比特率")
        self.video_bitrate_combo = _editable_combo(VIDEO_BITRATE_PRESETS)
        self.video_bitrate_combo.setCurrentText("auto")
        self.maximum_bitrate_combo = _editable_combo(MAX_BITRATE_PRESETS)
        self.maximum_bitrate_combo.setCurrentText("auto")
        self.size_lock_check = QCheckBox("锁定")
        self.file_size_edit = QLineEdit("-")
        self.file_size_edit.setAlignment(self.file_size_edit.alignment())
        self.file_size_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,6}(?:\.\d{0,2})?"))
        )
        self.file_size_edit.editingFinished.connect(self._target_size_changed)
        self.two_pass_check = QCheckBox("二次编码")
        self.highest_quality_check = QCheckBox("最高质量")

        self.audio_convert_check = QCheckBox("转换")
        self.audio_convert_check.toggled.connect(self._audio_changed)
        self.audio_codec_combo = QComboBox()
        for label, value in (
            ("复制", "copy"),
            ("AAC", "aac"),
            ("MP3", "mp3"),
            ("AC3", "ac3"),
            ("无音频", "none"),
        ):
            self.audio_codec_combo.addItem(label, value)
        self.audio_codec_combo.setCurrentIndex(self.audio_codec_combo.findData("aac"))
        self.audio_codec_combo.currentIndexChanged.connect(self._audio_codec_changed)
        self.audio_bitrate_combo = _editable_combo(AUDIO_BITRATE_PRESETS, numeric=True)
        self.audio_bitrate_combo.setCurrentText("256")
        self.audio_channels_combo = QComboBox()
        for label, value in (
            ("保持原样", "source"),
            ("单声道", "mono"),
            ("立体声", "stereo"),
            ("5.1", "5.1"),
        ):
            self.audio_channels_combo.addItem(label, value)
        self.audio_sample_rate_combo = QComboBox()
        for label, value in (
            ("保持原样", None),
            ("8 kHz", 8000),
            ("16 kHz", 16000),
            ("44.1 kHz", 44100),
            ("48 kHz", 48000),
            ("96 kHz", 96000),
            ("192 kHz", 192000),
        ):
            self.audio_sample_rate_combo.addItem(label, value)
        self.audio_sample_rate_combo.setCurrentIndex(self.audio_sample_rate_combo.findData(48000))

        self.hardware_decode_combo = QComboBox()
        self.hardware_decode_combo.addItem("自动", "auto")
        self.hardware_decode_combo.addItem("关闭", "none")
        for label, value in (
            ("CUDA", "cuda"),
            ("Intel QSV", "qsv"),
            ("D3D11VA", "d3d11va"),
            ("D3D12VA", "d3d12va"),
            ("DXVA2", "dxva2"),
        ):
            self.hardware_decode_combo.addItem(label, value)
        self.hardware_filter_combo = QComboBox()
        self.hardware_filter_combo.addItem("自动", "auto")
        self.hardware_filter_combo.addItem("关闭", "none")
        self.hardware_filter_combo.addItem("CUDA", "cuda")
        self.hardware_filter_combo.addItem("Intel QSV", "qsv")
        self.hardware_filter_combo.addItem("AMD AMF", "amf")
        self.video_encoder_combo = QComboBox()
        self.video_encoder_combo.addItem("CPU（libx264）", "cpu")
        self.video_encoder_combo.addItem("NVIDIA NVENC", "nvidia")
        self.video_encoder_combo.addItem("Intel QSV", "intel")
        self.video_encoder_combo.addItem("AMD AMF", "amd")
        self.video_encoder_combo.currentIndexChanged.connect(self._hardware_changed)

        self.suffix_mode = QComboBox()
        self.suffix_mode.addItem("自动编码后缀", "auto")
        self.suffix_mode.addItem("自定义后缀", "custom")
        self.suffix_mode.addItem("不追加后缀", "none")
        self.suffix_mode.currentIndexChanged.connect(self._suffix_mode_changed)
        self.custom_suffix = QLineEdit()
        self.custom_suffix.setPlaceholderText("例如：_兼容版")

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 7, 7, 6)
        root.setSpacing(4)
        checks = QHBoxLayout()
        checks.setSpacing(10)
        checks.addWidget(self.transcode_check)
        checks.addWidget(self.keep_source_check)
        checks.addStretch()
        root.addLayout(checks)
        self.image_group = self._image_group()
        self.bitrate_group = self._bitrate_group()
        self.audio_group = self._audio_group()
        self.hardware_group = self._hardware_group()
        self.output_group = self._output_group()
        for group in (
            self.image_group,
            self.bitrate_group,
            self.audio_group,
            self.hardware_group,
            self.output_group,
        ):
            root.addWidget(group)
        root.addStretch()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        for widget in (
            self.scale_combo,
            self.video_bitrate_combo,
            self.maximum_bitrate_combo,
            self.audio_bitrate_combo,
        ):
            widget.currentTextChanged.connect(self._update_file_size)
        self.size_lock_check.toggled.connect(self._size_lock_changed)
        self._rate_mode_changed()
        self._audio_changed()
        self._suffix_mode_changed()
        self._hardware_changed()

    def _form(self, fields: list[tuple[str | QWidget, QWidget]]) -> QFormLayout | QGridLayout:
        if not self.compact:
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(8)
            form.setVerticalSpacing(3)
            for label, field in fields:
                form.addRow(label, field)
            return form
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        for index, (label, field) in enumerate(fields):
            row = index // 2
            column = (index % 2) * 2
            grid.addWidget(label if isinstance(label, QWidget) else QLabel(label), row, column)
            grid.addWidget(field, row, column + 1)
            grid.setColumnStretch(column + 1, 1)
        return grid

    def _image_group(self) -> QGroupBox:
        group = QGroupBox("图像")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(7, 7, 7, 6)
        layout.setSpacing(3)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale_combo, 1)
        scale_row.addWidget(self.portrait_check)
        holder = QWidget()
        holder.setLayout(scale_row)
        layout.addLayout(
            self._form(
                [
                    ("比例", holder),
                    ("旋转", self.rotation_combo),
                    ("缩放算法", self.scale_algorithm),
                ]
            )
        )
        options = QHBoxLayout()
        options.addWidget(self.mirror_check)
        options.addWidget(self.force_dar_check)
        options.addWidget(self.no_upscale_check)
        options.addStretch()
        layout.addLayout(options)
        return group

    def _bitrate_group(self) -> QGroupBox:
        group = QGroupBox("比特率调整")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(7, 7, 7, 6)
        layout.setSpacing(3)
        size_row = QHBoxLayout()
        size_row.addWidget(self.file_size_edit, 1)
        size_row.addWidget(QLabel("MiB"))
        size_row.addWidget(self.size_lock_check)
        holder = QWidget()
        holder.setLayout(size_row)
        layout.addLayout(
            self._form(
                [
                    ("模式", self.rate_mode),
                    (self.video_bitrate_label, self.video_bitrate_combo),
                    ("最大限度", self.maximum_bitrate_combo),
                    ("文件大小", holder),
                ]
            )
        )
        options = QHBoxLayout()
        options.addWidget(self.two_pass_check)
        options.addWidget(self.highest_quality_check)
        options.addStretch()
        layout.addLayout(options)
        return group

    def _audio_group(self) -> QGroupBox:
        group = QGroupBox("音频设置")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(7, 7, 7, 6)
        layout.setSpacing(3)
        layout.addWidget(self.audio_convert_check)
        layout.addLayout(
            self._form(
                [
                    ("编码格式", self.audio_codec_combo),
                    ("音频比特率", self.audio_bitrate_combo),
                    ("声道", self.audio_channels_combo),
                    ("采样率", self.audio_sample_rate_combo),
                ]
            )
        )
        return group

    def _hardware_group(self) -> QGroupBox:
        group = QGroupBox("硬件加速")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(7, 7, 7, 6)
        layout.setSpacing(3)
        layout.addLayout(
            self._form(
                [
                    ("硬件解码", self.hardware_decode_combo),
                    ("硬件滤镜", self.hardware_filter_combo),
                    ("视频编码", self.video_encoder_combo),
                ]
            )
        )
        note = QLabel("仅启用实际检测可用的后端；不兼容的滤镜组合会回退软件处理。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#687386")
        layout.addWidget(note)
        return group

    def _output_group(self) -> QGroupBox:
        group = QGroupBox("文件与输出选项")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(7, 7, 7, 6)
        layout.setSpacing(3)
        layout.addLayout(
            self._form(
                [
                    ("文件后缀", self.suffix_mode),
                    ("自定义后缀", self.custom_suffix),
                ]
            )
        )
        return group

    @staticmethod
    def _combo_value(combo: QComboBox, fallback: str) -> str:
        value = combo.currentText().strip()
        return value or fallback

    def load_config(self, config: TranscodeConfig) -> None:
        self._updating = True
        try:
            self.transcode_check.setChecked(config.enabled)
            self.keep_source_check.setChecked(config.keep_source)
            self.scale_combo.setCurrentText(portrait_expression(config.scale, config.portrait))
            self.portrait_check.setChecked(config.portrait)
            self.rotation_combo.setCurrentIndex(max(0, self.rotation_combo.findData(config.rotation)))
            self.mirror_check.setChecked(config.mirror)
            self.force_dar_check.setChecked(config.force_display_aspect)
            self.no_upscale_check.setChecked(config.no_upscale)
            self.scale_algorithm.setCurrentIndex(max(0, self.scale_algorithm.findData(config.scale_algorithm)))
            self.rate_mode.setCurrentIndex(max(0, self.rate_mode.findData(config.rate_mode)))
            self._rate_mode_changed()
            if config.rate_mode == "cq":
                self.video_bitrate_combo.setCurrentText(str(config.quality))
            else:
                self.video_bitrate_combo.setCurrentText(config.video_bitrate)
            self.maximum_bitrate_combo.setCurrentText(config.maximum_bitrate)
            self.size_lock_check.setChecked(config.size_locked)
            self.file_size_edit.setText(str(config.target_size_mib or "-"))
            self.two_pass_check.setChecked(config.two_pass)
            self.highest_quality_check.setChecked(config.highest_quality)
            self.audio_convert_check.setChecked(config.audio_convert)
            self.audio_codec_combo.setCurrentIndex(max(0, self.audio_codec_combo.findData(config.audio_codec)))
            self.audio_bitrate_combo.setCurrentText(str(config.audio_bitrate_kbps or 256))
            self.audio_channels_combo.setCurrentIndex(max(0, self.audio_channels_combo.findData(config.audio_channels)))
            self.audio_sample_rate_combo.setCurrentIndex(
                max(0, self.audio_sample_rate_combo.findData(config.audio_sample_rate))
            )
            self.video_encoder_combo.setCurrentIndex(max(0, self.video_encoder_combo.findData(config.video_encoder)))
            self.hardware_decode_combo.setCurrentIndex(max(0, self.hardware_decode_combo.findData(config.hardware_decode)))
            self.hardware_filter_combo.setCurrentIndex(max(0, self.hardware_filter_combo.findData(config.hardware_filter)))
            self.suffix_mode.setCurrentIndex(max(0, self.suffix_mode.findData(config.suffix_mode)))
            self.custom_suffix.setText(config.custom_suffix)
        finally:
            self._updating = False
        self._audio_changed()
        self._hardware_changed()
        self._suffix_mode_changed()
        self._update_file_size()

    def to_config(
        self,
        *,
        enabled: bool | None = None,
        source_video_bitrate_kbps: int | None = None,
        source_video_codec: str = "",
    ) -> TranscodeConfig:
        mode = self.rate_mode.currentData()
        scale_value = self._combo_value(self.scale_combo, "源尺寸")
        scale = resolve_scale(
            scale_value,
            self._media_width,
            self._media_height,
            portrait=self.portrait_check.isChecked(),
            no_upscale=self.no_upscale_check.isChecked(),
        )
        video_value = self._combo_value(self.video_bitrate_combo, "auto")
        quality = 23
        if mode == "cq":
            if video_value == "最好":
                quality = 1
            elif video_value == "最差":
                quality = 51
            else:
                quality = max(1, min(51, int(video_value or 23)))
            video_value = "auto"
        else:
            resolve_video_bitrate(
                video_value,
                scale.width,
                scale.height,
                self._media_fps,
            )
        maximum_bitrate = self._combo_value(self.maximum_bitrate_combo, "auto")
        if maximum_bitrate.lower() != "auto":
            resolve_video_bitrate(
                maximum_bitrate,
                scale.width,
                scale.height,
                self._media_fps,
            )
        target_size = None
        if self.size_lock_check.isChecked():
            try:
                target_size = float(self.file_size_edit.text())
            except ValueError:
                target_size = None
        audio_codec = self.audio_codec_combo.currentData()
        try:
            audio_rate = int(self.audio_bitrate_combo.currentText())
        except ValueError:
            audio_rate = None
        audio_rate = clamp_audio_bitrate(audio_codec, audio_rate)
        return TranscodeConfig(
            enabled=self.transcode_check.isChecked() if enabled is None else enabled,
            keep_source=self.keep_source_check.isChecked(),
            scale=scale_value,
            portrait=self.portrait_check.isChecked(),
            rotation=self.rotation_combo.currentData(),
            mirror=self.mirror_check.isChecked(),
            force_display_aspect=self.force_dar_check.isChecked(),
            no_upscale=self.no_upscale_check.isChecked(),
            scale_algorithm=self.scale_algorithm.currentData(),
            rate_mode=mode,
            video_bitrate=video_value,
            maximum_bitrate=maximum_bitrate,
            quality=quality,
            target_size_mib=target_size,
            size_locked=self.size_lock_check.isChecked(),
            two_pass=self.two_pass_check.isChecked(),
            highest_quality=self.highest_quality_check.isChecked(),
            audio_convert=self.audio_convert_check.isChecked(),
            audio_codec=audio_codec,
            audio_bitrate_kbps=audio_rate,
            audio_channels=self.audio_channels_combo.currentData(),
            audio_sample_rate=self.audio_sample_rate_combo.currentData(),
            video_encoder=self.video_encoder_combo.currentData(),
            hardware_decode=self.hardware_decode_combo.currentData(),
            hardware_filter=self.hardware_filter_combo.currentData(),
            source_video_bitrate_kbps=source_video_bitrate_kbps,
            source_video_codec=source_video_codec,
            suffix_mode=self.suffix_mode.currentData(),
            custom_suffix=self.custom_suffix.text(),
        )

    def set_media_hint(
        self,
        width: int | None,
        height: int | None,
        fps: float | None,
        duration: float | None,
    ) -> None:
        self._media_width = width or 1920
        self._media_height = height or 1080
        self._media_fps = fps or 25.0
        self._media_duration = duration
        self._update_file_size()

    def set_available_hardware(self, availability: dict[str, bool]) -> None:
        self.hardware_availability = availability
        encoder_labels = {
            "nvidia": "NVIDIA NVENC",
            "intel": "Intel QSV",
            "amd": "AMD AMF",
        }
        for index in range(1, self.video_encoder_combo.count()):
            vendor = self.video_encoder_combo.itemData(index)
            available = availability.get(vendor, False)
            self.video_encoder_combo.model().item(index).setEnabled(available)
            self.video_encoder_combo.setItemText(
                index,
                encoder_labels[vendor] + ("" if available else "（不可用）"),
            )
        for combo, prefix in (
            (self.hardware_decode_combo, "decode_"),
            (self.hardware_filter_combo, "filter_"),
        ):
            for index in range(2, combo.count()):
                backend = combo.itemData(index)
                available = availability.get(f"{prefix}{backend}", False)
                combo.model().item(index).setEnabled(available)
                text = combo.itemText(index).replace("（不可用）", "")
                combo.setItemText(index, text + ("" if available else "（不可用）"))
            selected = combo.currentData()
            if selected not in {"auto", "none"} and not availability.get(f"{prefix}{selected}", False):
                combo.setCurrentIndex(combo.findData("auto"))
        if not availability.get(self.video_encoder_combo.currentData(), self.video_encoder_combo.currentData() == "cpu"):
            self.video_encoder_combo.setCurrentIndex(0)
        self._hardware_changed()

    def set_transcode_allowed(self, allowed: bool) -> None:
        self.transcode_check.setEnabled(allowed)

    def _portrait_changed(self, checked: bool) -> None:
        if self._updating:
            return
        self.scale_combo.setCurrentText(portrait_expression(self.scale_combo.currentText(), checked))
        self._update_file_size()

    def _rate_mode_changed(self) -> None:
        mode = self.rate_mode.currentData()
        current = self.video_bitrate_combo.currentText()
        self.video_bitrate_combo.blockSignals(True)
        self.video_bitrate_combo.clear()
        if mode == "cq":
            self.video_bitrate_label.setText("值")
            for value in ("最好", *range(1, 52), "最差"):
                self.video_bitrate_combo.addItem(str(value), value)
            self.video_bitrate_combo.setCurrentText(current if current.isdigit() else "23")
            self.file_size_edit.setText("-")
            self.file_size_edit.setEnabled(False)
            self.size_lock_check.setChecked(False)
        else:
            self.video_bitrate_label.setText("视频比特率")
            for value in VIDEO_BITRATE_PRESETS:
                self.video_bitrate_combo.addItem(str(value), value)
            self.video_bitrate_combo.setCurrentText(current if current in VIDEO_BITRATE_PRESETS else "auto")
            self.file_size_edit.setEnabled(True)
        self.video_bitrate_combo.blockSignals(False)
        self._hardware_changed()
        self._update_file_size()

    def _audio_codec_changed(self) -> None:
        codec = self.audio_codec_combo.currentData()
        defaults = {"aac": 256, "mp3": 256, "ac3": 384}
        if codec in defaults:
            self.audio_bitrate_combo.setCurrentText(str(defaults[codec]))
        self._audio_changed()

    def _audio_changed(self) -> None:
        enabled = self.audio_convert_check.isChecked()
        codec = self.audio_codec_combo.currentData()
        self.audio_codec_combo.setEnabled(enabled)
        transform = enabled and codec not in {"copy", "none"}
        self.audio_bitrate_combo.setEnabled(transform)
        self.audio_channels_combo.setEnabled(transform)
        self.audio_sample_rate_combo.setEnabled(transform)
        self._update_file_size()

    def _hardware_changed(self) -> None:
        cpu = self.video_encoder_combo.currentData() == "cpu"
        self.two_pass_check.setEnabled(cpu and self.rate_mode.currentData() in {"vbr", "cbr"})
        if not self.two_pass_check.isEnabled():
            self.two_pass_check.setChecked(False)

    def _size_lock_changed(self, checked: bool) -> None:
        self.file_size_edit.setReadOnly(not checked)
        if not checked:
            self._update_file_size()

    def _target_size_changed(self) -> None:
        if not self.size_lock_check.isChecked() or self.rate_mode.currentData() == "cq":
            return
        try:
            target = float(self.file_size_edit.text())
            audio = self._audio_bitrate()
            bitrate = bitrate_for_target_size(self._media_duration, target, audio)
        except ValueError:
            return
        self.video_bitrate_combo.setCurrentText(str(bitrate))

    def _audio_bitrate(self) -> int:
        if not self.audio_convert_check.isChecked():
            return 256
        try:
            return clamp_audio_bitrate(
                self.audio_codec_combo.currentData(),
                int(self.audio_bitrate_combo.currentText()),
            ) or 0
        except ValueError:
            return 0

    def _update_file_size(self) -> None:
        if self._updating or self.size_lock_check.isChecked() or self.rate_mode.currentData() == "cq":
            return
        try:
            scale = resolve_scale(
                self.scale_combo.currentText(),
                self._media_width,
                self._media_height,
                portrait=self.portrait_check.isChecked(),
                no_upscale=self.no_upscale_check.isChecked(),
            )
            bitrate = resolve_video_bitrate(
                self.video_bitrate_combo.currentText(),
                scale.width,
                scale.height,
                self._media_fps,
            )
            size = estimate_size_mib(self._media_duration, bitrate, self._audio_bitrate())
            self.file_size_edit.setText("-" if size is None else f"{size:.1f}")
        except ValueError:
            self.file_size_edit.setText("-")

    def _suffix_mode_changed(self) -> None:
        self.custom_suffix.setEnabled(self.suffix_mode.currentData() == "custom")
