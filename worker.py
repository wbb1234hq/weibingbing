import json
import os
from PyQt5.QtCore import QThread, pyqtSignal
import requests
import base64
import mimetypes
import re

class ProcessWorker(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    result = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, image_path, image_type, config):
        super().__init__()
        self.image_path = image_path
        self.image_type = image_type
        self.config = config
        self.should_stop = False

    def run(self):
        try:
            # 调用OCR API
            self.log.emit("正在进行OCR文字识别...")
            ocr_result = self.call_ocr_api()
            
            if not ocr_result:
                self.error.emit("OCR识别失败")
                return

            # 解析OCR结果
            try:
                result_data = json.loads(ocr_result)
                text_content = result_data.get("data", "")
                
                if not text_content:
                    self.error.emit("OCR识别结果为空")
                    return

                # 检查是否是系统提示词
                if text_content.startswith("作为") and ("文字秘书" in text_content or "文秘" in text_content):
                    self.log.emit("检测到系统提示词，跳过检查")
                    return

                self.log.emit(f"OCR识别结果: {text_content}")
                
                # 按句号分割文本，确保每句话都有结尾标点
                sentences = []
                current_sentence = ""
                for char in text_content:
                    current_sentence += char
                    if char in ['。', '！', '？', '…', '.', '!', '?']:
                        if current_sentence.strip():
                            sentences.append(current_sentence.strip())
                        current_sentence = ""
                if current_sentence.strip():  # 添加最后一句（如果没有结尾标点）
                    sentences.append(current_sentence.strip())
                
                total_sentences = len(sentences)
                processed_sentences = []
                
                for i, sentence in enumerate(sentences):
                    if self.should_stop:
                        break
                        
                    if not sentence.strip():
                        continue
                        
                    # 调用文字检查API
                    self.log.emit(f"正在检查第{i+1}/{total_sentences}句: {sentence}")
                    check_result = self.call_text_check_api(sentence)
                    
                    if check_result:
                        try:
                            check_data = json.loads(check_result)
                            processed_sentences.append({
                                "original": sentence,
                                "check_result": check_data
                            })
                        except json.JSONDecodeError:
                            self.log.emit(f"解析检查结果失败: {check_result}")
                            processed_sentences.append({
                                "original": sentence,
                                "check_result": json.dumps({"annotation": "无", "content_1": "无"})
                            })
                            
                    self.progress.emit(int((i + 1) * 100 / total_sentences))

                # 构建最终显示文本
                display_text = f"文件：{os.path.basename(self.image_path)}\n"
                display_text += "文本识别与检查结果：\n\n"
                display_text += "原始文本：\n"
                
                # 格式化原始文本，每行最大长度为50个字符
                line_length = 50
                for i in range(0, len(text_content), line_length):
                    display_text += text_content[i:i+line_length] + "\n"
                
                display_text += "\n详细检查结果：\n"
                
                for i, item in enumerate(processed_sentences, 1):
                    display_text += f"\n第{i}句：\n"
                    display_text += f"原文：{item['original']}\n"
                    if "check_result" in item:
                        check_data = item['check_result']
                        try:
                            if isinstance(check_data, str):
                                check_data = json.loads(check_data)
                            
                            if isinstance(check_data, dict):
                                annotation = check_data.get('annotation', '')
                                suggestion = check_data.get('content_1', '')
                                
                                # 检查是否包含错别字信息
                                has_typo = False
                                
                                # 检查annotation是否包含错别字信息
                                if annotation:
                                    # 查找"应改为"或"错误"等关键词，表示有错别字
                                    if "应改为" in annotation or "错误" in annotation or "错别字" in annotation:
                                        has_typo = True
                                        # 尝试提取错别字信息，优先使用"应改为"的表达方式
                                        matches = re.findall(r'"([^"]+)"\s*应改为\s*"([^"]+)"', annotation)
                                        if matches:
                                            # 使用第一个匹配结果
                                            old_word, new_word = matches[0]
                                            annotation = f'"{old_word}" 应改为 "{new_word}"'
                                        else:
                                            # 尝试提取错别字位置信息
                                            error_matches = re.search(r'([^（]+错误)', annotation)
                                            if error_matches:
                                                annotation = error_matches.group(1)
                                    # 检查是否包含"没有错别字"、"无错别字"等关键字
                                    elif any(phrase in annotation for phrase in ["没有错别字", "无错别字", "无误", "准确", "正确"]):
                                        annotation = "无"
                                    # 检查是否只有括号中的内容
                                    elif re.match(r'^（.*?）$', annotation):
                                        # 检查括号中是否包含机构名称等不是错别字的内容
                                        if "医院" in annotation or "大学" in annotation or "医科" in annotation:
                                            annotation = "无"
                                
                                # 处理建议内容
                                if suggestion:
                                    # 如果建议中包含"没有错别字"、"无错别字"等关键字
                                    if any(phrase in suggestion for phrase in ["没有错别字", "无错别字", "无误", "准确", "正确"]):
                                        if annotation == "无" or not has_typo:
                                            suggestion = "无"
                                    # 如果建议内容过长，尝试提取关键信息
                                    elif len(suggestion) > 100 and not has_typo:
                                        suggestion_matches = re.search(r'修改后的正确句子：\s*\n*(.+)', suggestion)
                                        if suggestion_matches:
                                            suggestion = suggestion_matches.group(1)
                                
                                # 如果annotation为空但suggestion有值
                                if not annotation or annotation == "无":
                                    # 尝试从suggestion中提取错别字信息
                                    if suggestion and suggestion != "无":
                                        typo_matches = re.search(r'"([^"]+)"\s*应改为\s*"([^"]+)"', suggestion)
                                        if typo_matches:
                                            old_word, new_word = typo_matches.group(1, 2)
                                            annotation = f'"{old_word}" 应改为 "{new_word}"'
                                            has_typo = True
                                
                                # 输出错别字信息
                                display_text += f"错别字：{annotation if has_typo or annotation != '无' else '无'}\n"
                                
                                # 输出建议信息
                                if suggestion and suggestion != "无":
                                    display_text += f"建议：{suggestion}\n"
                                else:
                                    display_text += "建议：无\n"
                            else:
                                display_text += "错别字：无\n"
                                display_text += "建议：无\n"
                        except json.JSONDecodeError:
                            display_text += "错别字：无\n"
                            display_text += "建议：无\n"
                    else:
                        display_text += "错别字：无\n"
                        display_text += "建议：无\n"
                    display_text += "--------------------------------------------------\n"
                
                self.result.emit(display_text)
                
            except json.JSONDecodeError as e:
                self.log.emit(f"JSON解析错误: {str(e)}")
                self.error.emit(f"解析返回数据失败: {str(e)}")
                return

            self.finished.emit()

        except Exception as e:
            self.log.emit(f"处理过程出错: {str(e)}")
            self.error.emit(str(e))

    def call_ocr_api(self):
        try:
            # 获取文件的完整路径并确保格式正确
            abs_path = os.path.abspath(self.image_path)
            # 确保使用正斜杠，避免Windows路径问题
            abs_path = abs_path.replace('\\', '/')
            
            # 检查文件是否存在
            if not os.path.exists(abs_path):
                error_msg = f"文件不存在: {abs_path}"
                self.log.emit(error_msg)
                self.error.emit(error_msg)
                return None
            
            # 修正API URL
            api_url = self.config['api_url'].replace('/fileOcrText', '/sync/pictureRecognition')
            
            # 打印详细的请求信息
            self.log.emit("\n==================== OCR API 请求信息 ====================")
            self.log.emit(f"请求URL: {api_url}")
            self.log.emit(f"请求方法: POST")
            self.log.emit(f"请求参数:")
            self.log.emit(f"  - 文件路径: {abs_path}")
            self.log.emit(f"  - 文件名: {os.path.basename(abs_path)}")
            self.log.emit(f"  - 文件大小: {os.path.getsize(abs_path)} 字节")
            self.log.emit("=====================================================\n")

            # 准备文件对象
            with open(abs_path, "rb") as f:
                url ='http://172.16.2.122:8064/agent-sales/gpt/fileOcrText'
                files = {"file": (abs_path, f)}
                response = requests.post(url=url, files=files)

            # 打印响应信息
            self.log.emit("\n==================== OCR API 响应信息 ====================")
            self.log.emit(f"响应状态码: {response.status_code}")
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    self.log.emit(f"响应数据: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
                    
                    # 检查响应结果
                    if response_data.get('code') == '000000':
                        # 提取识别文本
                        text_content = response_data.get('data', '')
                        if text_content:
                            self.log.emit("\n==================== OCR 识别结果 ====================")
                            self.log.emit("识别的文本内容：")
                            self.log.emit(text_content)
                            self.log.emit("=================================================\n")
                            return json.dumps(response_data)
                        else:
                            error_msg = "OCR识别结果为空"
                            self.log.emit(f"错误: {error_msg}")
                            self.error.emit(error_msg)
                    else:
                        error_msg = f"OCR API返回错误: {response_data.get('message', '未知错误')}"
                        self.log.emit(f"错误信息: {error_msg}")
                        self.error.emit(error_msg)
                except json.JSONDecodeError as e:
                    error_msg = f"解析响应JSON失败: {str(e)}"
                    self.log.emit(f"错误: {error_msg}")
                    self.log.emit(f"原始响应内容: {response.text}")
                    self.error.emit(error_msg)
            else:
                error_msg = f"OCR API请求失败: HTTP {response.status_code}"
                self.log.emit(f"错误信息: {error_msg}")
                try:
                    self.log.emit(f"响应内容: {response.text}")
                except:
                    pass
                self.error.emit(error_msg)
            self.log.emit("=====================================================\n")
            return None
            
        except Exception as e:
            error_msg = f"OCR API调用异常: {str(e)}"
            self.log.emit(f"\n==================== OCR API 错误信息 ====================")
            self.log.emit(error_msg)
            self.log.emit("=====================================================\n")
            self.error.emit(error_msg)
            return None

    def call_text_check_api(self, text):
        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.config["api_key"]}'
            }
            
            data = {
                'model': self.config['model'],
                'messages': [
                    {
                        'role': 'system',
                        'content': self.config['system_prompt']
                    },
                    {
                        'role': 'user',
                        'content': text
                    }
                ],
                'stream': False
            }
            
            self.log.emit(f"正在检查文本: {text}")
            
            response = requests.post(
                self.config['api2_url'],
                headers=headers,
                json=data
            )
            
            if response.status_code == 200:
                response_data = response.json()
                content = response_data.get('choices', [{}])[0].get('message', {}).get('content', '')
                if content:
                    try:
                        # 尝试解析为JSON
                        result = json.loads(content)
                        # 确保返回的是字典格式并转换为JSON字符串
                        if isinstance(result, dict):
                            return json.dumps(result)
                        else:
                            return json.dumps({"annotation": content, "content_1": content})
                    except json.JSONDecodeError:
                        # 如果不是JSON格式，将文本内容作为annotation返回
                        return json.dumps({"annotation": content, "content_1": content})
                return json.dumps({"annotation": "无", "content_1": "无"})
            else:
                error_msg = f"检查失败：HTTP {response.status_code}"
                self.log.emit(error_msg)
                return json.dumps({"annotation": error_msg, "content_1": error_msg})
                
        except Exception as e:
            error_msg = f"检查失败：{str(e)}"
            self.log.emit(error_msg)
            return json.dumps({"annotation": error_msg, "content_1": error_msg})

    def stop(self):
        self.should_stop = True 