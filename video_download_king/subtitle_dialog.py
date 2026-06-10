from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .models import SubtitleInfo, SubtitleSelection


class SubtitleDialog(QDialog):
    def __init__(
        self,
        options: list[SubtitleInfo],
        selected: list[SubtitleSelection],
        subtitle_format: str,
        show_all_automatic: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择字幕")
        self.resize(720, 560)
        self.options = options

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索语言代码或名称")
        self.search.textChanged.connect(self._apply_filter)
        self.show_all = QCheckBox("显示全部自动字幕")
        self.show_all.setChecked(show_all_automatic)
        self.show_all.toggled.connect(self._apply_filter)
        self.format_combo = QComboBox()
        self.format_combo.addItem("SRT", "srt")
        self.format_combo.addItem("VTT", "vtt")
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(subtitle_format)))

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.show_all)
        top.addWidget(QLabel("输出格式"))
        top.addWidget(self.format_combo)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["语言", "代码", "来源", "可用格式"])
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._item_changed)
        self.manual_group = QTreeWidgetItem(["人工字幕"])
        self.auto_group = QTreeWidgetItem(["自动字幕"])
        self.tree.addTopLevelItem(self.manual_group)
        self.tree.addTopLevelItem(self.auto_group)
        self._populate(selected)
        self.tree.expandAll()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(QLabel("同一语言同时存在人工和自动字幕时，只允许选择一种，优先保留人工字幕。"))
        layout.addWidget(self.tree, 1)
        layout.addWidget(buttons)
        self._apply_filter()

    def _populate(self, selected: list[SubtitleSelection]) -> None:
        selected_keys = {(item.language, item.kind) for item in selected}
        self.tree.blockSignals(True)
        for option in self.options:
            parent = self.manual_group if option.kind == "manual" else self.auto_group
            item = QTreeWidgetItem(
                [option.name, option.language, "人工" if option.kind == "manual" else "自动", ", ".join(option.formats)]
            )
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if (option.language, option.kind) in selected_keys else Qt.Unchecked)
            item.setData(0, Qt.UserRole, option)
            parent.addChild(item)
        self.tree.blockSignals(False)

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        option = item.data(0, Qt.UserRole)
        if not option or item.checkState(0) != Qt.Checked:
            return
        self.tree.blockSignals(True)
        for group in (self.manual_group, self.auto_group):
            for index in range(group.childCount()):
                other = group.child(index)
                other_option = other.data(0, Qt.UserRole)
                if other is not item and other_option and other_option.language == option.language:
                    other.setCheckState(0, Qt.Unchecked)
        self.tree.blockSignals(False)

    @staticmethod
    def _common_automatic(language: str) -> bool:
        value = language.lower()
        return value == "en" or value.startswith("en-") or value.startswith("zh")

    def _apply_filter(self) -> None:
        query = self.search.text().strip().lower()
        for group in (self.manual_group, self.auto_group):
            visible = 0
            for index in range(group.childCount()):
                item = group.child(index)
                option: SubtitleInfo = item.data(0, Qt.UserRole)
                matches = not query or query in option.language.lower() or query in option.name.lower()
                allowed = option.kind == "manual" or self.show_all.isChecked() or self._common_automatic(option.language)
                item.setHidden(not (matches and allowed))
                visible += int(matches and allowed)
            group.setHidden(visible == 0)

    def selections(self) -> list[SubtitleSelection]:
        result: list[SubtitleSelection] = []
        for group in (self.manual_group, self.auto_group):
            for index in range(group.childCount()):
                item = group.child(index)
                if item.checkState(0) == Qt.Checked:
                    option: SubtitleInfo = item.data(0, Qt.UserRole)
                    result.append(SubtitleSelection(option.language, option.kind))
        return result

    def subtitle_format(self) -> str:
        return self.format_combo.currentData()

    def show_all_automatic(self) -> bool:
        return self.show_all.isChecked()
