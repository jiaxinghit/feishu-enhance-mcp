#!/bin/bash

echo "========================================"
echo "  Lark MCP Server 启动脚本"
echo "========================================"
echo

if [ ! -f ".env" ]; then
    echo "[错误] 未找到 .env 配置文件"
    echo "请复制 .env.example 为 .env 并填写配置"
    exit 1
fi

echo "[信息] 检查Python环境..."
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未安装Python，请先安装Python 3.8+"
    exit 1
fi

echo "[信息] 安装依赖..."
pip3 install -r requirements.txt -q

echo "[信息] 启动 Lark MCP Server..."
echo "[提示] 此服务同时运行飞书长连接和MCP服务"
python3 lark_mcp_server.py
