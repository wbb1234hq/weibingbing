from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                           QLabel, QLineEdit, QDialogButtonBox, QTextEdit)

class ConfigDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config.copy()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("API配置")
        layout = QVBoxLayout(self)

        # # API URL配置（已屏蔽）
        # api_layout = QHBoxLayout()
        # api_layout.addWidget(QLabel("OCR API URL:"))
        # self.api_url_edit = QLineEdit(self.config.get('api_url', ''))
        # api_layout.addWidget(self.api_url_edit)
        # layout.addLayout(api_layout)

        # API2 URL配置
        api2_layout = QHBoxLayout()
        api2_layout.addWidget(QLabel("API URL:"))
        self.api2_url_edit = QLineEdit(self.config.get('api2_url', ''))
        api2_layout.addWidget(self.api2_url_edit)
        layout.addLayout(api2_layout)

        # API Key配置
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("API Key:"))
        self.api_key_edit = QLineEdit(self.config.get('api_key', ''))
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        key_layout.addWidget(self.api_key_edit)
        layout.addLayout(key_layout)

        # 模型配置
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("模型:"))
        self.model_edit = QLineEdit(self.config.get('model', 'deepseek-chat'))
        model_layout.addWidget(self.model_edit)
        layout.addLayout(model_layout)

        # System Prompt配置
        layout.addWidget(QLabel("System Prompt:"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setText(self.config.get('system_prompt', '作为一个细致耐心的文字秘书，对下面的句子进行错别字检查'))
        self.prompt_edit.setMinimumHeight(100)
        layout.addWidget(self.prompt_edit)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_config(self):
        # 使用现有的api_url值，不做修改
        self.config.update({
            # 'api_url': self.api_url_edit.text().strip(),  # 已屏蔽，不再获取
            'api2_url': self.api2_url_edit.text().strip(),
            'api_key': self.api_key_edit.text().strip(),
            'model': self.model_edit.text().strip(),
            'system_prompt': self.prompt_edit.toPlainText().strip()
        })
        return self.config 