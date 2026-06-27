@echo off
echo ========================================
echo  推送代码到GitHub
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] 检查git状态...
git status
echo.

echo [2/3] 添加所有文件...
git add .
echo.

echo [3/3] 推送到GitHub...
git push -u origin main
echo.

echo ========================================
echo  推送完成！
echo ========================================
pause