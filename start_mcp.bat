@echo off
chcp 65001 >nul
echo ========================================
echo   Lark MCP Server 启动脚本
echo ========================================
echo.

echo [信息] 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未安装Python，请先安装Python 3.10+
    pause
    exit /b 1
)

echo [信息] 启动 Lark MCP Server...
echo [提示] 此服务同时运行飞书长连接和MCP服务
python -m lark_mcp.server

pause
