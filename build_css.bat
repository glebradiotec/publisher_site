@echo off
echo Building Tailwind CSS...
tailwindcss.exe -i static\src\input.css -o static\tailwind.css --minify
echo Done!
pause
