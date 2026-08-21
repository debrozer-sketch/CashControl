"""
help_dialog.py — Справочник CashControl.

Открывается из сайдбара кнопкой «О программе».
Структура: дерево разделов слева, HTML-содержимое справа.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cashcontrol.gui.dialogs.help_content import _TREE


class HelpDialog(QDialog):
    """Справочник CashControl — дерево разделов + HTML."""

    def __init__(self, parent=None) -> None:
        super().__init__(None)
        self.setWindowTitle("Справочник CashControl v2")
        self.setMinimumSize(980, 680)
        self.resize(1100, 740)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self._pages: dict[QTreeWidgetItem, callable] = {}
        self._setup_ui()
        self._build_tree()
        root = self._tree.invisibleRootItem()
        if root.childCount():
            first = root.child(0)
            self._tree.setCurrentItem(first)
            self._show_page(first)

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(1)

        left = QWidget()
        left.setFixedWidth(230)
        try:
            from qfluentwidgets import isDarkTheme
            _dark = isDarkTheme()
        except Exception:
            _dark = False
        left.setStyleSheet("background: #1e2a3a;" if _dark else "background: #F0F4FA;")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        header = QLabel("  Содержание")
        header.setFixedHeight(40)
        header.setStyleSheet(
            "background: #1565C0; color: white; font-size: 13px; "
            "font-weight: 700; padding-left: 12px;"
        )
        ll.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        if _dark:
            self._tree.setStyleSheet("""
                QTreeWidget {
                    background: #1e2a3a;
                    color: #e0e0e0;
                    border: none;
                    font-size: 13px;
                    outline: none;
                }
                QTreeWidget::item {
                    padding: 5px 8px;
                    border-radius: 4px;
                }
                QTreeWidget::item:selected {
                    background: #0277bd;
                    color: white;
                }
                QTreeWidget::item:hover:!selected {
                    background: #1a3a5a;
                }
            """)
        else:
            self._tree.setStyleSheet("""
                QTreeWidget {
                    background: #F0F4FA;
                    border: none;
                    font-size: 13px;
                    outline: none;
                }
                QTreeWidget::item {
                    padding: 5px 8px;
                    border-radius: 4px;
                }
                QTreeWidget::item:selected {
                    background: #1565C0;
                    color: white;
                }
                QTreeWidget::item:hover:!selected {
                    background: #D8E4F5;
                }
            """)
        self._tree.currentItemChanged.connect(
            lambda cur, _prev: self._show_page(cur) if cur else None
        )
        ll.addWidget(self._tree, 1)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setStyleSheet("background: #1e1e1e;" if _dark else "background: white;")

        self._content_w = QLabel()
        self._content_w.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._content_w.setWordWrap(True)
        self._content_w.setTextFormat(Qt.TextFormat.RichText)
        self._content_w.setOpenExternalLinks(True)
        self._content_w.setContentsMargins(32, 24, 32, 32)
        self._content_w.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        scroll.setWidget(self._content_w)
        rl.addWidget(scroll, 1)
        splitter.addWidget(right)

        splitter.setSizes([230, 870])
        layout.addWidget(splitter)

    def _build_tree(self) -> None:
        for entry in _TREE:
            if len(entry) == 3:
                label, _, children = entry
                parent_item = QTreeWidgetItem(self._tree, [label])
                parent_item.setExpanded(True)
                for child_label, child_fn in children:
                    child_item = QTreeWidgetItem(parent_item, [child_label])
                    self._pages[child_item] = child_fn
            else:
                label, fn = entry
                item = QTreeWidgetItem(self._tree, [label])
                self._pages[item] = fn

    def _show_page(self, item: QTreeWidgetItem) -> None:
        fn = self._pages.get(item)
        if fn:
            self._content_w.setText(fn())
