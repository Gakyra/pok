import pyautogui
import time

print("=" * 50)
print("  ИНТЕРАКТИВНЫЙ КАЛИБРАТОР КООРДИНАТ ДЛЯ БОТА")
print("=" * 50)
print("Инструкция:")
print("Наведи курсор мыши на нужную кнопку или зону на столе.")
print("Нажми Ctrl+C в терминале, чтобы зафиксировать координаты.\n")

try:
    while True:
        x, y = pyautogui.position()
        position_str = f"Текущие координаты мыши: X = {x:>4}, Y = {y:>4}"
        print(position_str, end="\r")
        time.sleep(0.1)
except KeyboardInterrupt:
    print(f"\n\n[ЗАФИКСИРОВАНО] Координаты: X = {x}, Y = {y}")