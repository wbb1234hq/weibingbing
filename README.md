# 自动文字巡检工具 (Web版)

这是一个基于Flask的Web应用程序，用于图片文字识别和错别字检查。

## 功能特点

- 图片上传与预览
- 剪贴板图片粘贴
- OCR文字识别
- 错别字自动检查
- 结果导出为Excel
- API配置管理

## 技术栈

- 后端：Flask
- 前端：HTML, CSS, JavaScript, Bootstrap 5, jQuery
- 数据处理：Pandas
- 图像处理：Pillow

## 安装

1. 克隆仓库

```bash
git clone https://github.com/yourusername/text-proofreading-tool.git
cd text-proofreading-tool
```

2. 创建并激活虚拟环境（可选但推荐）

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python -m venv venv
source venv/bin/activate
```

3. 安装依赖

```bash
pip install -r web_requirements.txt
```

## 配置

首次运行应用程序时，将在项目根目录创建一个默认的`config.json`文件。您可以通过应用程序的Web界面或直接编辑此文件进行配置：

```json
{
  "api_url": "",
  "api2_url": "https://api.deepseek.com/chat/completions",
  "api_key": "",
  "model": "deepseek-chat",
  "system_prompt": "作为一个细致耐心的文字秘书，对下面的句子进行错别字检查"
}
```

## 运行应用

```bash
flask run
```

然后在浏览器中访问：`http://127.0.0.1:5000/`

## 部署

### 使用Gunicorn（Linux/macOS）

```bash
gunicorn -w 4 app:app
```

### 使用Waitress（Windows）

```bash
pip install waitress
waitress-serve --port=8000 app:app
```

## 使用方法

1. **上传图片**：
   - 拖放图片到上传区域
   - 点击上传区域选择图片文件
   - 使用Ctrl+V粘贴剪贴板中的图片

2. **处理图片**：
   - 在图片列表中点击"识别"按钮
   - 等待处理完成

3. **查看结果**：
   - 在"识别结果"标签页查看详细结果
   - 在"处理日志"标签页查看处理过程日志

4. **导出结果**：
   - 点击"导出为Excel"按钮
   - 选择保存位置

5. **配置API**：
   - 点击导航栏中的"配置"
   - 设置API URL和API Key等参数

## 注意事项

- 请确保有足够的磁盘空间，上传的图片会临时保存在服务器上
- 对于大文件，处理可能需要较长时间
- API密钥不会在前端页面显示，但会保存在配置文件中，请确保配置文件的安全性

## 许可证

MIT #   w e i b i n g b i n g  
 