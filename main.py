import sys
import warnings
import json
import base64
import os
import uuid
import re
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QTextEdit, QLabel, 
                            QTabWidget, QLineEdit, QProgressBar, QFileDialog,
                            QMessageBox, QScrollArea, QFrame)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QBuffer, QByteArray, QUrl
from PyQt5.QtGui import QClipboard, QImage, QPainter, QColor, QPixmap
import requests
from datetime import datetime
import io
from PIL import Image
from worker import ProcessWorker
from config_dialog import ConfigDialog
from io import BytesIO
from PIL import ImageGrab

# 忽略 PyQt5 的废弃警告
warnings.filterwarnings("ignore", category=DeprecationWarning)

class APIConfigTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        
        # API配置
        api_group = QWidget()
        api_layout = QVBoxLayout()
        self.api_url = QLineEdit()
        self.api_url.setPlaceholderText("API URL")
        self.question = QLineEdit()
        self.question.setPlaceholderText("识别问题")
        self.question.setText("识别图片中的内容，识别出的内容逐句进行错别字勘误，如果有错误输出这句话和错误内容，没有错误输出原文")
        api_layout.addWidget(QLabel("API配置"))
        api_layout.addWidget(self.api_url)
        api_layout.addWidget(QLabel("识别问题"))
        api_layout.addWidget(self.question)
        api_group.setLayout(api_layout)
        
        layout.addWidget(api_group)
        
        # 保存按钮
        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self.save_config)
        layout.addWidget(save_btn)
        
        self.setLayout(layout)
        self.load_config()

    def save_config(self):
        config = {
            'api_url': self.api_url.text(),
            'question': self.question.text()
        }
        try:
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "成功", "配置已保存")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置失败：{str(e)}")

    def load_config(self):
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.api_url.setText(config.get('api_url', ''))
                self.question.setText(config.get('question', '识别图片中的内容，识别出的内容逐句进行错别字勘误，如果有错误输出这句话和错误内容，没有错误输出原文'))
        except:
            pass

    def get_config(self):
        return {
            'api_url': self.api_url.text(),
            'question': self.question.text()
        }

class ImagePasteArea(QTextEdit):
    image_pasted = pyqtSignal(QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setPlaceholderText("在此处粘贴图片（Ctrl+V）")
        self.setMinimumHeight(200)
        self.setStyleSheet("QTextEdit { background-color: white; border: 1px solid #ccc; }")

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.toPlainText() and not self.document().isEmpty():
            painter = QPainter(self.viewport())
            painter.setPen(QColor(128, 128, 128))
            painter.drawText(self.rect(), Qt.AlignCenter, "在此处粘贴图片（Ctrl+V）")

    def insertFromMimeData(self, source):
        self.clear()  # 每次粘贴都先清空文本内容
        if source.hasImage():
            image = source.imageData()
            self.document().addResource(
                1,  # QTextDocument.ImageResource
                QUrl("data://image.png"),
                image
            )
            self.textCursor().insertImage("data://image.png")
            self.image_pasted.emit(image)
            return  # 只处理图片，不插入其他内容
        elif source.hasUrls():
            for url in source.urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                    image = QImage(file_path)
                    if not image.isNull():
                        self.document().addResource(
                            1,  # QTextDocument.ImageResource
                            QUrl("data://image.png"),
                            image
                        )
                        self.textCursor().insertImage("data://image.png")
                        self.image_pasted.emit(image)
                        return  # 只处理图片，不插入其他内容
            # 如果是文件路径但不是图片，直接return，不插入任何内容
            return
        # 只有不是图片/文件路径时，才走父类方法
        super().insertFromMimeData(source)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自动文字巡检工具")
        self.setMinimumSize(800, 600)
        
        # 创建临时文件夹
        self.temp_dir = os.path.join(os.getcwd(), 'temp')
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
        
        # 初始化配置
        self.config = self.load_config()
        
        # 初始化UI
        self.init_ui()
        
        # 初始化worker
        self.worker = None
        self.current_image = None
        self.current_image_path = None
        self.current_image_type = None

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # 创建顶部按钮区域
        button_layout = QHBoxLayout()
        self.upload_btn = QPushButton("上传图片")
        self.start_btn = QPushButton("开始识别")
        self.stop_btn = QPushButton("停止")
        self.config_btn = QPushButton("配置")

        self.stop_btn.setEnabled(False)
        
        button_layout.addWidget(self.upload_btn)
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addWidget(self.config_btn)
        
        layout.addLayout(button_layout)

        # 创建图片粘贴区域
        paste_layout = QVBoxLayout()
        paste_label = QLabel("可在此粘贴图片 (Ctrl+V):")
        self.image_paste_area = ImagePasteArea()
        self.image_paste_area.image_pasted.connect(self.on_image_pasted)
        
        paste_layout.addWidget(paste_label)
        paste_layout.addWidget(self.image_paste_area)
        
        layout.addLayout(paste_layout)

        # 创建图片展示区容器
        self.images_container = QWidget()
        self.images_layout = QVBoxLayout(self.images_container)
        self.images_layout.setAlignment(Qt.AlignTop)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.images_container)
        
        # 创建选项卡
        self.tab_widget = QTabWidget()
        
        # 图片预览区域
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.addWidget(scroll_area)
        
        # 结果显示区域
        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        
        # 添加导出按钮
        export_btn = QPushButton("导出为Excel")
        export_btn.clicked.connect(self.export_to_excel)
        
        result_layout.addWidget(self.result_text)
        result_layout.addWidget(export_btn)
        result_widget.setLayout(result_layout)
        
        # 日志显示区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        self.tab_widget.addTab(preview_widget, "图片预览")
        self.tab_widget.addTab(result_widget, "识别结果")
        self.tab_widget.addTab(self.log_text, "处理日志")
        
        layout.addWidget(self.tab_widget)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 连接信号
        self.upload_btn.clicked.connect(self.upload_image)
        self.start_btn.clicked.connect(self.start_process)
        self.stop_btn.clicked.connect(self.stop_process)
        self.config_btn.clicked.connect(self.show_config)
        
        # 图片列表和结果列表
        self.image_items = []
        self.result_data = []  # 用于存储识别结果数据，方便导出

    def load_config(self):
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {
                'api_url': '',
                'api2_url': '',
                'api_key': '',
                'model': 'deepseek-chat',
                'system_prompt': '作为一个细致耐心的文字秘书，对下面的句子进行错别字检查'
            }

    def save_config(self):
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def upload_image(self):
        # 清除之前的图片
        if self.current_image_path and os.path.exists(self.current_image_path):
            try:
                os.remove(self.current_image_path)
                self.log_text.append("已清除前一张图片")
            except Exception as e:
                self.log_text.append(f"清除前一张图片失败: {str(e)}")

        # 重置图片预览
        self.image_paste_area.clear()
        self.current_image_path = None
        self.current_image_type = None

        file_name, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_name:
            self.load_image(file_name)
            self.log_text.append("已上传新图片")

    def on_image_pasted(self, image):
        # 将QImage转换为字节数据
        buffer = QBuffer()
        buffer.open(QBuffer.WriteOnly)
        image.save(buffer, "PNG")
        image_data = buffer.data().data()
        
        # 加载图片并自动开始处理
        self.load_image_data(image_data, auto_start=True)
        self.log_text.append("已粘贴新图片并开始处理")
        
        # 自动清空粘贴图片框和文件地址
        QApplication.processEvents()  # 确保UI更新
        self.image_paste_area.clear()
        self.image_paste_area.document().clear()  # 完全清空文档

    def paste_image(self):
        # 获取新图片
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasImage():
            # 从剪贴板获取QImage
            image = clipboard.image()
            if not image.isNull():
                # 将QImage转换为字节数据
                buffer = QBuffer()
                buffer.open(QBuffer.WriteOnly)
                image.save(buffer, "PNG")
                image_data = buffer.data().data()
                self.load_image_data(image_data)
                self.log_text.append("已粘贴新图片")
                return
                
        # 尝试从PIL获取图片
        pil_image = ImageGrab.grabclipboard()
        if isinstance(pil_image, Image.Image):
            buffer = BytesIO()
            pil_image.save(buffer, format='PNG')
            self.load_image_data(buffer.getvalue())
            self.log_text.append("已粘贴新图片")
            return
            
        # 检查是否有文件路径
        if mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                    try:
                        with open(file_path, 'rb') as f:
                            self.load_image_data(f.read())
                            self.log_text.append("已粘贴新图片")
                            return
                    except:
                        pass

        QMessageBox.warning(self, "警告", "剪贴板中没有可用的图片")

    def load_image(self, file_path):
        with open(file_path, 'rb') as f:
            self.load_image_data(f.read())

    def load_image_data(self, image_data, auto_start=False):
        # 生成唯一的临时文件名
        temp_filename = f"temp_{uuid.uuid4().hex[:8]}_{int(datetime.now().timestamp())}.png"
        image_path = os.path.join(self.temp_dir, temp_filename)
        image_type = 'image/png'
        
        # 保存图片到临时文件
        with open(image_path, 'wb') as f:
            f.write(image_data)
        
        # 创建新的图片项
        item_widget = QWidget()
        item_layout = QVBoxLayout(item_widget)
        
        # 图片预览
        image_preview = QLabel()
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        
        # 计算合适的尺寸，保持宽高比
        max_width = 600
        if pixmap.width() > max_width:
            scaled_pixmap = pixmap.scaledToWidth(max_width, Qt.SmoothTransformation)
        else:
            scaled_pixmap = pixmap
        
        image_preview.setPixmap(scaled_pixmap)
        
        # 添加删除按钮
        btn_layout = QHBoxLayout()
        delete_btn = QPushButton("删除")
        process_btn = QPushButton("识别")
        
        btn_layout.addWidget(delete_btn)
        btn_layout.addWidget(process_btn)
        
        # 添加文件名标签
        file_label = QLabel(f"文件: {temp_filename}")
        
        item_layout.addWidget(file_label)
        item_layout.addWidget(image_preview)
        item_layout.addLayout(btn_layout)
        
        # 添加分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        
        # 添加到图片容器
        self.images_layout.insertWidget(0, item_widget)
        self.images_layout.insertWidget(1, line)
        
        # 保存图片信息
        image_info = {
            'widget': item_widget,
            'separator': line,
            'path': image_path,
            'type': image_type,
            'preview': image_preview,
            'delete_btn': delete_btn,
            'process_btn': process_btn
        }
        
        self.image_items.insert(0, image_info)
        
        # 连接按钮信号
        delete_btn.clicked.connect(lambda: self.delete_image(image_info))
        process_btn.clicked.connect(lambda: self.process_image(image_info))
        
        # 自动开始处理
        if auto_start:
            self.process_image(image_info)
        
        self.current_image_path = image_path
        self.current_image_type = image_type
        self.start_btn.setEnabled(True)

    def delete_image(self, image_info):
        # 从界面移除
        self.images_layout.removeWidget(image_info['widget'])
        self.images_layout.removeWidget(image_info['separator'])
        image_info['widget'].deleteLater()
        image_info['separator'].deleteLater()
        
        # 删除文件
        if os.path.exists(image_info['path']):
            try:
                os.remove(image_info['path'])
            except:
                pass
                
        # 从列表移除
        self.image_items.remove(image_info)
        
        # 更新当前图片
        if self.image_items:
            self.current_image_path = self.image_items[0]['path']
            self.current_image_type = self.image_items[0]['type']
        else:
            self.current_image_path = None
            self.current_image_type = None
            self.start_btn.setEnabled(False)

    def process_image(self, image_info):
        self.current_image_path = image_info['path']
        self.current_image_type = image_info['type']
        self.start_process()

    def start_process(self):
        if not self.current_image_path:
            QMessageBox.warning(self, "警告", "请先上传或粘贴图片")
            return
            
        if not self.config.get('api2_url'):
            QMessageBox.warning(self, "警告", "请先配置API信息")
            return

        self.worker = ProcessWorker(self.current_image_path, self.current_image_type, self.config)
        self.worker.progress.connect(self.update_progress)
        self.worker.log.connect(self.update_log)
        self.worker.result.connect(self.update_result)
        self.worker.error.connect(self.show_error)
        self.worker.finished.connect(self.process_finished)
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.worker.start()

    def stop_process(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(True)

    def show_config(self):
        dialog = ConfigDialog(self.config, self)
        if dialog.exec_():
            self.config = dialog.get_config()
            self.save_config()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_log(self, message):
        self.log_text.append(message)

    def update_result(self, text):
        # 解析文本中的文件名和内容
        filename_match = re.search(r"文件：(.*?)\n", text)
        filename = filename_match.group(1) if filename_match else "未知文件"
        
        # 提取原始文本内容
        original_text_match = re.search(r"原始文本：\n(.*?)\n\n详细检查结果", text, re.DOTALL)
        original_text = original_text_match.group(1).strip() if original_text_match else ""
        
        # 提取所有句子检查结果
        sentences_data = []
        sentence_pattern = re.compile(r"第(\d+)句：\n原文：(.*?)\n错别字：(.*?)\n建议：(.*?)\n-{10,}", re.DOTALL)
        for match in sentence_pattern.finditer(text):
            sentence_num = match.group(1)
            original = match.group(2).strip()
            error = match.group(3).strip()
            suggestion = match.group(4).strip()

            # 新增：判断错别字字段是否为常见无错别字短语
            no_typo_phrases = [
                "没有错别字", "无错别字", "无误", "准确", "正确", "经过检查，句子中没有错别字", "句子中没有错别字"
            ]
            error_clean = error.replace("。", "").replace("，", "").replace(" ", "")
            is_no_typo = any(phrase in error_clean for phrase in no_typo_phrases)

            sentences_data.append({
                "文件名称": filename,
                "句子编号": sentence_num,
                "原文": original,
                "错别字": "" if error == "无" or is_no_typo else error,
                "建议": suggestion
            })
        
        # 将数据添加到结果列表
        self.result_data.extend(sentences_data)
        
        # 在开头添加时间戳和分隔线
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80
        formatted_text = f"{separator}\n{timestamp}\n{separator}\n\n{text}\n\n"
        
        # 添加到现有文本的顶部而不是替换
        current_text = self.result_text.toPlainText()
        self.result_text.setText(formatted_text + current_text)
        self.tab_widget.setCurrentIndex(1)  # 切换到结果标签页

    def show_error(self, message):
        QMessageBox.critical(self, "错误", message)
        self.stop_process()

    def process_finished(self):
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(True)

    def closeEvent(self, event):
        # 清理临时文件
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                try:
                    os.remove(os.path.join(self.temp_dir, file))
                except:
                    pass
            try:
                os.rmdir(self.temp_dir)
            except:
                pass
        super().closeEvent(event)

    def export_to_excel(self):
        if not self.result_data:
            QMessageBox.warning(self, "警告", "没有可导出的数据")
            return
        
        # 创建Excel文件名（含年月）
        current_date = datetime.now()
        filename = f"自动文字巡检结果{current_date.year}年{current_date.month}月.xlsx"
        
        # 选择保存路径
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存Excel文件", filename, "Excel文件 (*.xlsx)"
        )
        
        if not file_path:
            return  # 用户取消了保存
        
        try:
            # 创建DataFrame
            df = pd.DataFrame(self.result_data)
            
            # 保存为Excel
            df.to_excel(file_path, index=False)
            
            QMessageBox.information(self, "成功", f"数据已成功导出到 {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_()) 