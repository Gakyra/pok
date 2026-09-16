import time
import random
import math
import pyautogui
import numpy as np

# Отключаем мгновенную остановку PyAutoGUI при упирании в угол экрана
pyautogui.FAILSAFE = False


class Humanizer:
    def __init__(self):
        # Базовые настройки экрана (PyAutoGUI)
        pyautogui.PAUSE = 0.01

    @staticmethod
    def wait_thinking_time(min_sec=1.5, max_sec=4.0):
        """
        Имитирует раздумья человека перед ходом.
        Использует гауссово распределение, чтобы большинство задержек
        были в районе середины интервала.
        """
        mean = (min_sec + max_sec) / 2
        std_dev = (max_sec - min_sec) / 6  # 99.7% значений попадут в диапазон
        delay = random.gauss(mean, std_dev)

        # Ограничиваем жесткими рамками
        clamped_delay = max(min_sec, min(max_sec, delay))
        time.sleep(clamped_delay)

    @staticmethod
    def _generate_bezier_curve(p0, p1, p2, p3, num_points=20):
        """Генерирует точки гладкой кривой Безье между кнопками."""
        t = np.linspace(0, 1, num_points)
        curve = (
                (1 - t) ** 3 * np.array(p0)[:, None] +
                3 * (1 - t) ** 2 * t * np.array(p1)[:, None] +
                3 * (1 - t) * t ** 2 * np.array(p2)[:, None] +
                t ** 3 * np.array(p3)[:, None]
        )
        return curve.T

    def move_mouse_human(self, target_x, target_y, radius_offset=5):
        """
        Двигает мышь к цели по физиологичной дуге с легким дрожанием.
        `radius_offset` отвечает за рандомное смещение внутри кнопки.
        """
        start_x, start_y = pyautogui.position()

        # 1. Рандомизируем финальную точку внутри самой кнопки (не кликаем в один пиксель)
        final_x = target_x + random.randint(-radius_offset, radius_offset)
        final_y = target_y + radius_offset + random.randint(-radius_offset, radius_offset)

        # 2. Создаем опорные контрольные точки для кривой (изгиб движения)
        control_distance = math.hypot(final_x - start_x, final_y - start_y)
        deviation = control_distance * random.uniform(0.1, 0.3)

        ctrl1_x = start_x + (final_x - start_x) * 0.25 + random.uniform(-deviation, deviation)
        ctrl1_y = start_y + (final_y - start_y) * 0.25 + random.uniform(-deviation, deviation)

        ctrl2_x = start_x + (final_x - start_x) * 0.75 + random.uniform(-deviation, deviation)
        ctrl2_y = start_y + (final_y - start_y) * 0.75 + random.uniform(-deviation, deviation)

        # 3. Строим путь
        points = self._generate_bezier_curve(
            (start_x, start_y),
            (ctrl1_x, ctrl1_y),
            (ctrl2_x, ctrl2_y),
            (final_x, final_y),
            num_points=random.randint(15, 25)
        )

        # 4. Движение с ускорением и замедлением к концу пути
        for pt in points:
            pyautogui.moveTo(pt[0], pt[1])
            time.sleep(random.uniform(0.005, 0.015))

    def human_click(self, x, y, button_radius=8):
        """
        Полный цикл человеческого клика:
        Пауза на подумать -> Плавный подвод мыши -> Микропауза перед кликом -> Клик
        """
        # Пауза перед решением
        self.wait_thinking_time(min_sec=1.2, max_sec=3.5)

        # Движение мыши к цели
        self.move_mouse_human(x, y, radius_offset=button_radius)

        # Небольшое замирание курсора перед нажатием (человек прицеливается)
        time.sleep(random.uniform(0.08, 0.25))

        # Зажатие и отпускание кнопки (тоже с микрозадержкой)
        pyautogui.mouseDown()
        time.sleep(random.uniform(0.04, 0.09))
        pyautogui.mouseUp()


# Проверочный запуск
if __name__ == "__main__":
    human = Humanizer()
    print("Тестируем человеческий клик... Курсор двинется через 2 секунды.")
    time.sleep(2)
    # Пример: кликнуть в координаты X=500, Y=500
    human.human_click(500, 500)
    print("Клик выполнен!")