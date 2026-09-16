import time
from pynput import keyboard, mouse

# Глобальный контроллер мыши для снятия текущих координат
mouse_controller = mouse.Controller()

print("=" * 60)
print("   СКРИПТ ЗАМЕРА КООРДИНАТ ДЛЯ ПОЛЗУНКА ПОКЕРА")
print("=" * 60)
print("Инструкция:")
print("1. Открой окно с покером.")
print("2. Наведи курсор на ЛЕВЫЙ край ползунка (мин. ставка) и нажми SHIFT.")
print("3. Наведи курсор на ПРАВЫЙ край ползунка (олл-ин) и нажми SHIFT.")
print("4. Для выхода нажми ESC.")
print("=" * 60)

coords_history = []


def on_press(key):
  try:
    # Отслеживаем нажатие клавиши Shift
    if key == keyboard.Key.shift or key == keyboard.Key.shift_r:
      x, y = mouse_controller.position
      coords_history.append((x, y))
      count = len(coords_history)

      if count == 1:
        print(f"\n[1] ЛЕВЫЙ КРАЙ (slider_left_x)  : X = {x}, Y = {y}")
      elif count == 2:
        print(f"[2] ПРАВЫЙ КРАЙ (slider_right_x): X = {x}, Y = {y}")

        # Считаем средний Y и ширину
        avg_y = (coords_history[0][1] + coords_history[1][1]) // 2
        width = coords_history[1][0] - coords_history[0][0]

        print("\n" + "-" * 50)
        print("ГОТОВЫЕ ПАРАМЕТРЫ ДЛЯ TableDetector:")
        print(f"slider_left_x  = {coords_history[0][0]}")
        print(f"slider_right_x = {coords_history[1][0]}")
        print(f"slider_y       = {avg_y}")
        print(f"Ширина ползунка: {width}px")
        print("-" * 50)
        print("\nЗамер окончен! Можешь нажать ESC для выхода.")

    elif key == keyboard.Key.esc:
      print("\nВыход из программы...")
      return False  # Остановка слушателя

  except Exception as e:
    print(f"Ошибка: {e}")


# Запуск слушателя клавиатуры
with keyboard.Listener(on_press=on_press) as listener:
  listener.join()