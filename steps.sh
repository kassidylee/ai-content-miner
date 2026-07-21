#!/bin/bash
# steps.sh - 一键部署脚本

echo "🚀 AI Content Miner 一键部署"

# 1. 克隆 MediaCrawler
echo "📡 克隆 MediaCrawler..."
git clone https://github.com/NanmiCoder/MediaCrawler.git

# 2. 安装 MediaCrawler 依赖
echo "📦 安装 MediaCrawler 依赖..."
cd MediaCrawler
pip install -r requirements.txt
playwright install
cd ..

# 3. 安装本项目依赖
echo "📦 安装本项目依赖..."
pip install -r requirements.txt

# 4. 配置提示
echo ""
echo "⚠️ 请编辑 config.py，填写以下配置："
echo "   - API_KEY"
echo "   - WECOM_WEBHOOK"
echo "   - REPORT_BASE_URL"
echo ""

# 5. 启动预览服务
echo "📁 启动预览服务..."
echo "   python server.py"

# 6. 运行工作流
echo "🚀 运行工作流..."
echo "   python main.py"