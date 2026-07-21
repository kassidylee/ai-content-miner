# 1. 克隆 MediaCrawler
git clone https://github.com/NanmiCoder/MediaCrawler.git

# 2. 安装 MediaCrawler 依赖
cd MediaCrawler
pip install -r requirements.txt
playwright install
cd ..

# 3. 安装本项目依赖
pip install -r requirements.txt

# 4. 配置 config.py（填写 API_KEY、WECOM_WEBHOOK 等）

# 5. 启动预览服务
python server.py

# 6. 运行全自动工作流
python main.py