from PySide6.QtWidgets import QVBoxLayout, QWizardPage
from qfluentwidgets import BodyLabel, TitleLabel

from cashcontrol import __app_name__, __version__


class WelcomePage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Добро пожаловать")
        self.setSubTitle(f"{__app_name__} v{__version__}")

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(40, 20, 40, 20)

        title = TitleLabel(f"Добро пожаловать в {__app_name__} 3.0", self)
        layout.addWidget(title)

        desc = BodyLabel(
            "Эта программа предназначена для удалённого управления "
            "и мониторинга кассовых терминалов.", self)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        features = BodyLabel(
            "• Подключение к кассам POS, SCO, Touch по SSH\n"
            "• Мониторинг состояния: DNS, CPU, ОС, ФР\n"
            "• Выполнение команд на кассах\n"
            "• VNC-просмотр экрана кассы", self)
        features.setWordWrap(True)
        layout.addWidget(features)
        layout.addStretch()