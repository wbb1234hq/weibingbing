import os
import uuid
import json
import re
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, url_for, redirect
from werkzeug.utils import secure_filename
from PIL import Image
import io
import base64
import requests
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'hard-to-guess-string'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 限制上传文件大小为16MB

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # 输出到控制台
        logging.FileHandler('app.log', encoding='utf-8')  # 同时输出到文件
    ]
)
logger = logging.getLogger(__name__)

# 添加全局变量到所有模板
@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 加载配置
def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        default_config = {
            'api_url': '',
            'api2_url': 'https://api.deepseek.com/chat/completions',
            'api_key': '',
            'model': 'deepseek-chat',
            'system_prompt': '作为一个细致耐心的文字秘书，对下面的句子进行错别字检查',
            'kimi_api_key': '',  # Kimi API密钥
            'kimi_upload_url': 'https://api.moonshot.cn/v1/files'  # Kimi文件上传API的URL
        }
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config

# 全局保存处理结果数据
results_data = []

@app.route('/')
def index():
    config = load_config()
    return render_template('index.html', config=config)

@app.route('/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
        new_config = {
            'api2_url': request.form.get('api2_url', 'https://api.deepseek.com/chat/completions'),
            'api_key': request.form.get('api_key', ''),
            'model': request.form.get('model', 'deepseek-chat'),
            'system_prompt': request.form.get('system_prompt', '作为一个细致耐心的文字秘书，对下面的句子进行错别字检查'),
            'kimi_api_key': request.form.get('kimi_api_key', ''),
            'kimi_upload_url': request.form.get('kimi_upload_url', 'https://api.moonshot.cn/v1/files')
        }
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(new_config, f, ensure_ascii=False, indent=2)
        return redirect(url_for('index'))
    
    config = load_config()
    return render_template('config.html', config=config)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '没有文件上传'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': '没有选择文件'})
    
    if file:
        # 生成唯一文件名
        filename = f"temp_{uuid.uuid4().hex[:8]}_{int(datetime.now().timestamp())}"
        ext = os.path.splitext(file.filename)[1]
        full_filename = secure_filename(filename + ext)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], full_filename)
        
        # 保存文件
        file.save(filepath)
        
        # 确保返回的路径使用正斜杠
        normalized_filepath = filepath.replace('\\', '/')
        logger.info(f"上传文件保存路径: {filepath}, 标准化后: {normalized_filepath}")
        
        return jsonify({
            'success': True, 
            'filename': full_filename,
            'filepath': normalized_filepath,
            'preview_url': url_for('static', filename=f'uploads/{full_filename}')
        })

@app.route('/process', methods=['POST'])
def process_image():
    global results_data
    
    data = request.json
    image_path = data.get('filepath')
    
    # 确保路径使用系统分隔符
    if image_path:
        image_path = image_path.replace('/', os.sep).replace('\\\\', os.sep)
        logger.info(f"处理图片路径: 原始={data.get('filepath')}, 转换后={image_path}")
    
    if not image_path or not os.path.exists(image_path):
        error_msg = f"文件不存在: {image_path}"
        logger.error(error_msg)
        return jsonify({'success': False, 'message': error_msg})
    
    config = load_config()
    
    try:
        # 调用OCR API
        ocr_result = call_ocr_api(image_path, config)
        
        if not ocr_result:
            return jsonify({'success': False, 'message': 'OCR识别失败'})
        
        # 解析OCR结果
        result_data = json.loads(ocr_result)

        print("result_data",result_data)

        # text_content = result_data.get("data", "")

        # 1. 解析 data 字段（它是 JSON 字符串）
        data_dict = json.loads(result_data['data'])

        # 2. 获取 content 的值
        text_content = data_dict['content']

        print("text_content",text_content)
        if not text_content:
            return jsonify({'success': False, 'message': 'OCR识别结果为空'})
        
        # 检查是否是系统提示词
        # if text_content.startswith("作为") and ("文字秘书" in text_content or "文秘" in text_content):
        #     return jsonify({'success': False, 'message': '检测到系统提示词，跳过检查'})
        
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
        
        processed_sentences = []
        
        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue
            
            # 调用文字检查API
            check_result = call_text_check_api(sentence, config)
            
            if check_result:
                try:
                    check_data = json.loads(check_result)
                    processed_sentences.append({
                        "original": sentence,
                        "check_result": check_data
                    })
                except json.JSONDecodeError:
                    processed_sentences.append({
                        "original": sentence,
                        "check_result": json.dumps({"annotation": "无", "content_1": "无"})
                    })
        
        # 构建最终显示文本
        display_text = f"文件：{os.path.basename(image_path)}\n"
        display_text += "文本识别与检查结果：\n\n"
        display_text += "原始文本：\n"
        
        # 格式化原始文本，每行最大长度为50个字符
        line_length = 50
        for i in range(0, len(text_content), line_length):
            display_text += text_content[i:i+line_length] + "\n"
        
        display_text += "\n详细检查结果：\n"
        
        # 准备结果数据
        sentence_results = []
        
        for i, item in enumerate(processed_sentences, 1):
            display_text += f"\n第{i}句：\n"
            display_text += f"原文：{item['original']}\n"
            
            typo_text = "无"
            suggestion_text = "无"
            
            if "check_result" in item:
                check_data = item['check_result']
                try:
                    if isinstance(check_data, str):
                        check_data = json.loads(check_data)
                    
                    if isinstance(check_data, dict):
                        # 获取wrong字段和其他内容
                        is_wrong = check_data.get("wrong", False)
                        original_content = check_data.get("content_0", item['original'])
                        annotation = check_data.get('annotation', '')
                        suggestion = check_data.get('content_1', '')
                        
                        # 根据wrong字段决定是否显示错别字
                        if is_wrong:
                            # wrong=true时，显示annotation作为错别字
                            typo_text = annotation
                            suggestion_text = suggestion if suggestion and suggestion != "无" else "无"
                            logger.info(f"检测到错别字 - wrong=true: {typo_text}")
                        else:
                            # wrong=false时，不显示错别字
                            typo_text = "无"
                            suggestion_text = "无"
                            logger.info(f"无错别字 - wrong=false")
                        
                        # 调试输出
                        logger.info(f"句子处理: wrong={is_wrong}, typo_text={typo_text}, suggestion={suggestion_text}")
                except Exception as e:
                    logger.error(f"处理检查结果时出错: {str(e)}")
                    pass
            
            display_text += f"错别字：{typo_text}\n"
            display_text += f"建议：{suggestion_text}\n"
            display_text += "--------------------------------------------------\n"
            
            # 添加到结果数据中
            sentence_results.append({
                "文件名称": os.path.basename(image_path),
                "句子编号": str(i),
                "原文": item['original'],
                "错别字": typo_text if typo_text != "无" else "",
                "建议": suggestion_text if suggestion_text != "无" else ""
            })
        
        # 添加到全局结果数据
        results_data.extend(sentence_results)
        
        return jsonify({
            'success': True,
            'result': display_text,
            'sentences': sentence_results
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'处理过程出错: {str(e)}'})

def call_ocr_api(image_path, config):
    try:
        # 获取文件的完整路径
        abs_path = os.path.abspath(image_path)
        
        # 检查文件是否存在
        if not os.path.exists(abs_path):
            logger.error(f"文件不存在: {abs_path}")
            return None
        
        # 从配置获取Kimi API密钥和URL
        kimi_api_key = config.get('kimi_api_key', '')
        kimi_upload_url = config.get('kimi_upload_url', 'https://api.moonshot.cn/v1/files')
        
        if not kimi_api_key:
            logger.error("Kimi API密钥未配置")
            return None
            
        # 设置请求头
        headers = {
            "Authorization": f"Bearer {kimi_api_key}"
        }
        
        # 上传文件
        logger.info(f"开始上传文件: {abs_path}")
        with open(abs_path, "rb") as file:
            # 准备文件数据
            files = {
                "file": (os.path.basename(abs_path), file)
            }
            # 发起 POST 请求上传文件
            upload_response = requests.post(kimi_upload_url, headers=headers, files=files)
        
        # 输出上传响应以便调试
        logger.info(f"上传响应状态码: {upload_response.status_code}")
        logger.info(f"上传响应内容: {upload_response.text}")
        
        # 检查上传响应状态
        if upload_response.status_code == 200:
            try:
                upload_data = upload_response.json()
                file_id = upload_data.get('id')
                
                if not file_id:
                    logger.error("上传成功但获取文件ID失败")
                    return None
                
                logger.info(f"获取到的文件ID: {file_id}")
                
                # 获取文件内容 - 直接构建完整的URL
                content_url = f"https://api.moonshot.cn/v1/files/{file_id}/content"
                logger.info(f"请求文件内容URL: {content_url}")
                
                content_response = requests.get(content_url, headers=headers)
                
                # 输出内容响应以便调试
                logger.info(f"内容响应状态码: {content_response.status_code}")
                if content_response.status_code != 200:
                    logger.error(f"内容响应错误: {content_response.text}")
                
                if content_response.status_code == 200:
                    # 构造与原先API相同格式的返回结果
                    text_content = content_response.text
                    logger.info(f"成功获取到文本内容，长度: {len(text_content)}")
                    result_data = {
                        "code": "000000",
                        "data": text_content,
                        "message": "成功"
                    }
                    return json.dumps(result_data)
                else:
                    logger.error(f"获取文件内容失败，状态码：{content_response.status_code}")
                    logger.error(f"错误详情: {content_response.text}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"解析上传响应失败: {upload_response.text}")
                logger.error(f"JSON解析错误: {str(e)}")
                return None
            except Exception as e:
                logger.error(f"处理上传响应时发生错误: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                return None
        else:
            logger.error(f"文件上传失败，状态码：{upload_response.status_code}")
            logger.error(f"错误详情: {upload_response.text}")
            return None
                
    except Exception as e:
        logger.error(f"OCR API调用出错: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def call_text_check_api(text, config):
    try:
        # 获取配置参数
        api_url = config.get('api2_url', 'https://api.deepseek.com/chat/completions')
        api_key = config.get('api_key', '')
        model = config.get('model', 'deepseek-chat')
        
        # 获取系统提示词
        system_prompt = config.get("system_prompt", "作为一个细致耐心的文字秘书，对下面的句子进行错别字检查，按如下结构以 JSON 格式输出：\n{\n\"content_0\":\"原始句子\",\n\"wrong\":true,//是否有需要被修正的错别字，布尔类型\n\"annotation\":\"\",//批注内容，string类型。如果wrong为true给出修正的解释；如果 wrong 字段为 false，则为空值\n\"content_1\":\"\"//修改后的句子，string类型。如果wrong为false则留空\n}")
        
        if not api_key:
            logger.error("文字检查API密钥未配置")
            return json.dumps({"annotation": "API密钥未配置", "content_1": "请配置API密钥"})
        
        # 构建请求头和数据
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key}"
        }
        
        # 处理输入文本
        processed_text = text
        
        # 构建请求数据 - 修复JSON序列化问题
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": processed_text}
            ],
            "stream": False,
            # 添加max_tokens参数
            "max_tokens": 1024
        }
        
        # 序列化请求数据
        json_data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        
        # 记录请求详情
        _log_api_request(api_url, headers, model, system_prompt, text, data)
        
        # 发送请求
        start_time = datetime.now()
        response = requests.post(api_url, headers=headers, data=json_data)
        
        # 记录请求响应的全部信息
        logger.info(f"Request URL: {api_url}")
        logger.info(f"Request Headers: {headers}")
        logger.info(f"Request Body: {json_data.decode('utf-8')}")
        logger.info(f"Response Status: {response.status_code}")
        logger.info(f"Response Headers: {response.headers}")
        logger.info(f"Response Body: {response.text}")
        
        end_time = datetime.now()
        response_time = (end_time - start_time).total_seconds()
        
        # 记录响应详情
        _log_api_response(end_time, response_time, response.status_code, response.text)
        
        # 处理成功响应
        if response.status_code == 200:
            return _process_successful_response_new(response)
        
        # 处理错误响应
        return _process_error_response(response.status_code)
    
    except Exception as e:
        error_details = f"处理错误: {str(e)}"
        logger.error(error_details)
        import traceback
        logger.error(traceback.format_exc())
        return json.dumps({"annotation": error_details, "content_1": "请联系管理员或检查网络连接"}, ensure_ascii=False)

def _fix_incomplete_json(text):
    """修复不完整的JSON字符串"""
    fixed_text = text
    if '"' in fixed_text and fixed_text.count('"') % 2 != 0:
        fixed_text += '"'
    if fixed_text.count('{') > fixed_text.count('}'):
        fixed_text += '}'
    logger.info(f"修复后的文本: {fixed_text}")
    return fixed_text

def _log_api_request(api_url, headers, model, system_prompt, text, data):
    """记录API请求详情"""
    logger.info(f"\n==================== 文字检查API请求信息 ====================")
    logger.info(f"请求时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"请求URL: {api_url}")
    logger.info(f"请求方法: POST")
    # 隐藏敏感信息
    sanitized_headers = headers.copy()
    if 'Authorization' in sanitized_headers:
        auth_parts = sanitized_headers['Authorization'].split(' ')
        if len(auth_parts) > 1:
            sanitized_headers['Authorization'] = f"{auth_parts[0]} {'*' * 8}{auth_parts[1][-4:]}"
    logger.info(f"请求头(脱敏): {json.dumps(sanitized_headers, ensure_ascii=False, indent=2)}")
    logger.info(f"模型: {model}")
    logger.info(f"系统提示词: {system_prompt}")
    logger.info(f"检查文本: {text}")
    logger.info(f"请求体: {json.dumps(data, ensure_ascii=False, indent=2)}")
    logger.info("==============================================================\n")

def _log_api_response(end_time, response_time, status_code, response_text):
    """记录API响应详情"""
    logger.info(f"\n==================== 文字检查API响应信息 ====================")
    logger.info(f"响应时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"请求耗时: {response_time:.3f}秒")
    logger.info(f"响应状态码: {status_code}")
    
    if len(response_text) > 500:
        logger.info(f"响应内容(前500字符): {response_text[:500]}...")
        logger.info(f"响应内容(后500字符): ...{response_text[-500:]}")
        logger.info(f"响应内容长度: {len(response_text)}字符")
    else:
        logger.info(f"响应内容: {response_text}")
    logger.info("==============================================================\n")

def _process_successful_response_new(response):
    """处理成功的API响应，使用新的JSON格式"""
    try:
        # 解析API响应
        response_data = response.json()
        
        # 从响应中提取助手消息内容
        if 'choices' in response_data and len(response_data['choices']) > 0:
            content = response_data['choices'][0]['message']['content']
            logger.info(f"助手回复: {content}")
            
            # 预处理：去除可能的代码块标记
            # 检查是否包含 ```json 或 ``` 标记
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]  # 去除开头的 ```json
            elif content.startswith("```"):
                content = content[3:]  # 去除开头的 ```
                
            if content.endswith("```"):
                content = content[:-3]  # 去除结尾的 ```
                
            content = content.strip()
            
            # 尝试解析为JSON
            try:
                json_content = json.loads(content)
                logger.info(f"成功解析为JSON: {json_content}")
                
                # 检查wrong字段
                is_wrong = json_content.get("wrong", False)
                
                # 创建结果
                result = {
                    "wrong": is_wrong,  # 添加wrong字段到结果中
                    "annotation": json_content.get("annotation", "") if is_wrong else "无",
                    "content_1": json_content.get("content_1", "") if is_wrong else "无"
                }
                
                logger.info(f"处理结果: {result}")
                return json.dumps(result, ensure_ascii=False)
                
            except json.JSONDecodeError as e:
                # JSON解析失败，记录详细错误并尝试进一步处理
                logger.warning(f"JSON解析错误: {str(e)}")
                logger.warning(f"尝试解析的内容: {content}")
                
                # 尝试更宽容的解析方式
                try:
                    # 使用正则表达式提取JSON部分
                    import re
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                        logger.info(f"提取到的JSON字符串: {json_str}")
                        json_content = json.loads(json_str)
                        
                        # 检查wrong字段
                        is_wrong = json_content.get("wrong", False)
                        
                        # 创建结果
                        result = {
                            "wrong": is_wrong,  # 添加wrong字段到结果中
                            "annotation": json_content.get("annotation", "") if is_wrong else "无",
                            "content_1": json_content.get("content_1", "") if is_wrong else "无"
                        }
                        
                        logger.info(f"处理结果(备选解析): {result}")
                        return json.dumps(result, ensure_ascii=False)
                    else:
                        # 没有找到JSON结构，使用文本处理
                        return _process_text_content(content)
                except Exception as json_e:
                    logger.warning(f"备选JSON解析也失败: {str(json_e)}")
                    # 所有JSON解析方法都失败，使用文本处理
                    return _process_text_content(content)
        else:
            logger.error(f"响应格式不正确: {response_data}")
            return json.dumps({"wrong": False, "annotation": "API响应格式不正确", "content_1": "请联系管理员"})
    except Exception as e:
        error_details = f"处理API响应时出错: {str(e)}"
        logger.error(error_details)
        import traceback
        logger.error(traceback.format_exc())
        return json.dumps({"wrong": False, "annotation": error_details, "content_1": "请联系管理员"})

def _process_text_content(content):
    """处理文本格式的内容"""
    logger.warning(f"返回内容不是有效的JSON格式: {content}")
    
    # 检查是否包含"没有错别字"等关键词
    no_error_keywords = ["没有错别字", "无错别字", "无错误", "无拼写错误", "无需修改", "无误", "准确", "正确"]
    if any(phrase in content.lower() for phrase in no_error_keywords):
        return json.dumps({"annotation": "无", "content_1": "无"}, ensure_ascii=False)
    
    # 尝试从文本中提取错别字信息
    # 增强正则表达式，支持更多格式
    error_match = re.search(r'错别字[:：](.*?)(?:建议[:：]|$)', content, re.DOTALL)
    
    # 如果上面的方式没找到，尝试查找"应为"或"应该是"的模式
    if not error_match:
        # 查找"X应为Y"或"X应该是Y"格式
        typo_match = re.search(r'[""「](.+?)[""」]\s*应(?:该)?[为是]\s*[""「](.+?)[""」]', content)
        if typo_match:
            old_word, correct_word = typo_match.group(1), typo_match.group(2)
            error = f'"{old_word}" 应改为 "{correct_word}"'
            logger.info(f"使用'应为'模式提取到错别字: {error}")
            return json.dumps({"annotation": error, "content_1": content}, ensure_ascii=False)
    
    suggestion_match = re.search(r'建议[:：](.*?)$', content, re.DOTALL)
    
    error = error_match.group(1).strip() if error_match else "无"
    suggestion = suggestion_match.group(1).strip() if suggestion_match else "无"
    
    # 如果错误信息为"无"，但内容中有明显的错别字提示，尝试进一步分析
    if error == "无" and ("错别字" in content or "应为" in content or "应改为" in content):
        # 尝试查找格式为"X是错别字，应为Y"的模式
        alt_match = re.search(r'[""「](.+?)[""」].*?错别字.*?应(?:该)?[为是]\s*[""「](.+?)[""」]', content, re.DOTALL)
        if alt_match:
            old_word, correct_word = alt_match.group(1), alt_match.group(2)
            error = f'"{old_word}" 应改为 "{correct_word}"'
            logger.info(f"使用备用模式提取到错别字: {error}")
    
    # 如果无法提取到具体的错别字或建议，则使用全文作为建议
    if error == "无" and suggestion == "无":
        result = {"annotation": "无", "content_1": content}
    else:
        result = {"annotation": error, "content_1": suggestion}
    
    return json.dumps(result, ensure_ascii=False)

def _process_error_response(status_code):
    """根据状态码处理错误响应"""
    # 状态码到错误信息的映射
    error_map = {
        400: ("API请求格式不正确(400)", "请检查API参数和模型名称是否正确"),
        401: ("API认证失败(401)", "请检查API密钥是否正确"),
        403: ("API权限不足(403)", "请确认API密钥有足够的权限"),
        404: ("API接口不存在(404)", "请检查API URL是否正确"),
        429: ("API请求过多(429)", "请降低请求频率或提高API限额")
    }
    
    # 获取错误信息和解决方案
    if status_code in error_map:
        error_message, solution = error_map[status_code]
    elif status_code >= 500:
        error_message = f"API服务器错误({status_code})"
        solution = "请稍后重试或联系API服务提供商"
    else:
        error_message = f"API请求失败: {status_code}"
        solution = "请检查API配置"
    
    logger.error(f"错误: {error_message}")
    logger.error(f"解决方案: {solution}")
    
    return json.dumps({"annotation": error_message, "content_1": solution}, ensure_ascii=False)

@app.route('/paste', methods=['POST'])
def paste_image():
    data = request.json
    if not data or 'image_data' not in data:
        return jsonify({'success': False, 'message': '没有收到图片数据'})
    
    image_data = data['image_data']
    # 去除base64前缀
    if ',' in image_data:
        image_data = image_data.split(',')[1]
    
    try:
        # 解码base64数据
        image_bytes = base64.b64decode(image_data)
        # 打开图片
        image = Image.open(io.BytesIO(image_bytes))
        
        # 生成唯一文件名
        filename = f"paste_{uuid.uuid4().hex[:8]}_{int(datetime.now().timestamp())}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # 保存图片
        image.save(filepath)
        
        # 确保返回的路径使用正斜杠
        normalized_filepath = filepath.replace('\\', '/')
        logger.info(f"图片保存路径: {filepath}, 标准化后: {normalized_filepath}")
        
        return jsonify({
            'success': True,
            'filename': filename,
            'filepath': normalized_filepath,
            'preview_url': url_for('static', filename=f'uploads/{filename}')
        })
    
    except Exception as e:
        logger.error(f"处理粘贴图片失败: {str(e)}")
        return jsonify({'success': False, 'message': f'处理图片失败: {str(e)}'})

@app.route('/export', methods=['GET'])
def export_excel():
    global results_data
    
    if not results_data:
        return jsonify({'success': False, 'message': '没有可导出的数据'})
    
    try:
        # 创建Excel文件名（含年月）
        current_date = datetime.now()
        filename = f"自动文字巡检结果{current_date.year}年{current_date.month}月.xlsx"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # 创建DataFrame
        df = pd.DataFrame(results_data)
        
        # 保存为Excel
        df.to_excel(filepath, index=False)
        
        # 返回文件下载链接
        return jsonify({
            'success': True,
            'download_url': url_for('download_file', filename=filename)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'导出失败: {str(e)}'})

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)

@app.route('/clear_results', methods=['POST'])
def clear_results():
    global results_data
    results_data = []
    return jsonify({'success': True})

@app.route('/delete_image', methods=['POST'])
def delete_image():
    data = request.json
    if not data or 'filepath' not in data:
        return jsonify({'success': False, 'message': '未提供文件路径'})
    
    filepath = data['filepath']
    
    try:
        # 确保路径使用系统分隔符
        filepath = filepath.replace('/', os.sep).replace('\\\\', os.sep)
        logger.info(f"准备删除文件: 原始路径={data['filepath']}, 转换后={filepath}")
        
        # 检查文件是否存在
        if os.path.exists(filepath):
            # 删除文件
            os.remove(filepath)
            logger.info(f"已删除文件: {filepath}")
            return jsonify({'success': True})
        else:
            # 文件已经不存在
            logger.warning(f"文件不存在: {filepath}")
            return jsonify({'success': True, 'message': '文件已不存在'})
    except Exception as e:
        logger.error(f"删除文件失败: {str(e)}")
        return jsonify({'success': False, 'message': f"删除失败: {str(e)}"})

if __name__ == '__main__':
    app.run(debug=True) 