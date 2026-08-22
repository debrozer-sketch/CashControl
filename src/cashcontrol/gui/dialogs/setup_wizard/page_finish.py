from PySide6.QtWidgets import QVBoxLayout, QWizardPage
from qfluentwidgets import BodyLabel, SubtitleLabel


class FinishPage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Настройка завершена")
        self.setSubTitle("Проверьте параметры и начните работу")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 20, 40, 20)

        self.header = SubtitleLabel("", self)
        layout.addWidget(self.header)

        self.detail = BodyLabel("", self)
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        layout.addStretch()

    def initializePage(self) -> None:
        w = self.wizard()
        self.header.setText("Всё готово к работе")
        self.detail.setText(
            f"SSH:     {w.field('ssh_login') or 'tc'} : {w.field('ssh_port') or '22'}\n"
            f"DB:      {w.field('db_login') or 'postgres'} : {w.field('db_port') or '5432'}"
        )

    def isComplete(self) -> bool:
        return True