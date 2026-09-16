import os
import time
import cv2
import mss
import numpy as np
import pyautogui

# Импортируем класс Humanizer из вашего файла humanizer.py
from humanizer import Humanizer


class TableDetector:

  def __init__(
      self,
      templates_dir="templates",
      slider_left_x=287,
      slider_right_x=1020,
      slider_y=781,
      base_window_width=1280,
      base_window_height=720,
  ):
    # Относительные/абсолютные координаты ползунка
    self.rel_left = slider_left_x
    self.rel_right = slider_right_x
    self.rel_y = slider_y
    self.base_w = base_window_width
    self.base_h = base_window_height

    # Путь к папке с шаблонами
    self.templates_dir = templates_dir
    self.templates = {}

    # Захват экрана и хуманизатор
    self.sct = mss.mss()
    self.human = Humanizer()

    # Загружаем файлы кнопок при старте
    self.load_templates()

  def get_absolute_slider_coords(self, table_region=None):
    """Рассчитывает абсолютные координаты ползунка под размер окна."""
    if not table_region:
      return self.rel_left, self.rel_right, self.rel_y

    win_left = table_region.get("left", 0)
    win_top = table_region.get("top", 0)
    win_w = table_region.get("width", self.base_w)
    win_h = table_region.get("height", self.base_h)

    scale_x = win_w / self.base_w
    scale_y = win_h / self.base_h

    abs_left_x = win_left + int(self.rel_left * scale_x)
    abs_right_x = win_left + int(self.rel_right * scale_x)
    abs_y = win_top + int(self.rel_y * scale_y)

    return abs_left_x, abs_right_x, abs_y

  def load_templates(self):
    """Загрузка всех кнопок-шаблонов из папки templates."""
    if not os.path.exists(self.templates_dir):
      os.makedirs(self.templates_dir)
      print(
          f"[WARNING] Папка '{self.templates_dir}' создана. Поместите туда"
          " шаблоны!"
      )
      return

    for file_name in os.listdir(self.templates_dir):
      if file_name.endswith((".png", ".jpg")):
        name = os.path.splitext(file_name)[0]
        path = os.path.join(self.templates_dir, file_name)
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is not None:
          self.templates[name] = img
          print(f"[VISION] Загружен шаблон: {name}")

  def find_template_on_screen(
      self, template_name, region=None, threshold=0.8
  ):
    """Поиск элемента на экране с помощью OpenCV."""
    if template_name not in self.templates:
      print(f"[ERROR] Шаблон '{template_name}' не найден в памяти!")
      return None

    monitor = region if region else self.sct.monitors[1]
    sct_img = self.sct.grab(monitor)
    screen_img = np.array(sct_img)[:, :, :3]

    template = self.templates[template_name]
    th, tw = template.shape[:2]

    result = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
      center_x = max_loc[0] + tw // 2 + monitor.get("left", 0)
      center_y = max_loc[1] + th // 2 + monitor.get("top", 0)
      return (center_x, center_y)

    return None

  def set_slider_bet(
      self, target_bet, min_bet, max_bet, table_region=None
  ):
    """Вычисляет пропорцию на ползунке и делает сглаженный human-клик."""
    abs_left_x, abs_right_x, abs_y = self.get_absolute_slider_coords(
        table_region
    )

    target_bet = max(min_bet, min(target_bet, max_bet))
    ratio = (
        0.0
        if max_bet == min_bet
        else (target_bet - min_bet) / (max_bet - min_bet)
    )

    slider_width = abs_right_x - abs_left_x
    target_x = abs_left_x + int(slider_width * ratio)

    print(
        f"[SLIDER] Ставка ${target_bet} (Мин: ${min_bet}, Макс: ${max_bet}) ->"
        f" Клик в (X: {target_x}, Y: {abs_y})"
    )
    self.human.human_click(target_x, abs_y)
    time.sleep(0.15)

  def prepare_raise(
      self, target_bet, min_bet, max_bet, table_region=None
  ):
    """Передвигает ползунок на нужную сумму и ждет ручного подтверждения."""
    print(f"\n[AI ANALYTICS] Выставляем ползунок под ставку: ${target_bet}")
    self.set_slider_bet(target_bet, min_bet, max_bet, table_region)
    print("=" * 60)
    print(f"[WAIT] Ползунок передвинут на ${target_bet}!")
    print(" -> Проверь сумму на экране.")
    print(" -> Нажми кнопку 'BET / RAISE' на столе сам.")
    print("=" * 60)

  def execute_action(
      self,
      action_type,
      bet_amount=None,
      min_bet=1.0,
      max_bet=100.0,
      table_region=None,
      auto_confirm=False,
  ):
    """Выполнение действия на столе (fold, call, raise)."""
    if action_type == "fold":
      pos = self.find_template_on_screen("btn_fold", region=table_region)
      if pos:
        self.human.human_click(pos[0], pos[1])
        print(f"[ACTION] Нажата кнопка FOLD в {pos}")
      else:
        print("[ACTION ERROR] Кнопка FOLD не найдена")

    elif action_type == "call":
      pos = self.find_template_on_screen("btn_call", region=table_region)
      if pos:
        self.human.human_click(pos[0], pos[1])
        print(f"[ACTION] Нажата кнопка CALL в {pos}")
      else:
        print("[ACTION ERROR] Кнопка CALL не найдена")

    elif action_type == "raise":
      if bet_amount is not None:
        self.set_slider_bet(bet_amount, min_bet, max_bet, table_region)

      if auto_confirm:
        raise_pos = self.find_template_on_screen(
            "btn_raise", region=table_region
        )
        if raise_pos:
          self.human.human_click(raise_pos[0], raise_pos[1])
          print(
              f"[ACTION] Выполнен RAISE (${bet_amount}) через клик по кнопке"
          )
        else:
          print("[ACTION ERROR] Кнопка RAISE не найдена для клика")
      else:
        print(f"[ACTION] Ползунок выставлен на ${bet_amount}. Ждем клика!")


if __name__ == "__main__":
  # Твои зафиксированные параметры
  detector = TableDetector(
      slider_left_x=287,
      slider_right_x=1020,
      slider_y=781,
      base_window_width=1280,
      base_window_height=720,
  )
  print("\n--- ТЕСТИРОВАНИЕ ПОИСКА КНОПОК И ПОЛЗУНКА ---")

  # Проверяем поиск шаблонов
  for template_key in ["btn_call", "btn_fold", "btn_raise"]:
    if template_key in detector.templates:
      coords = detector.find_template_on_screen(template_key)
      if coords:
        print(f"[OK] Кнопка '{template_key}' найдена в координатах: {coords}")
      else:
        print(f"[?] Кнопка '{template_key}' не видна на экране.")

  print("\n[TEST] Тестируем движение ползунка...")
  detector.prepare_raise(target_bet=35, min_bet=2, max_bet=100)