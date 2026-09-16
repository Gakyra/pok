import cv2
import numpy as np
from mss import mss
import pytesseract


# Если Tesseract установлен по стандартному пути в Windows:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class PokerVision:
    def __init__(self):
        self.sct = mss()

    def capture_zone(self, x, y, width, height):
        """
        Мгновенно захватывает определенную область экрана в оперативную память.
        """
        monitor = {"top": y, "left": x, "width": width, "height": height}
        screenshot = np.array(self.sct.grab(monitor))
        # Преобразуем из BGRA в BGR для OpenCV
        return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

    def read_number_from_zone(self, zone_img):
        """
        Считывает числа (размер банка, стеки, ставки) из захваченной области.
        """
        # Переводим в оттенки серого для лучшего распознавания
        gray = cv2.cvtColor(zone_img, cv2.COLOR_BGR2GRAY)

        # Увеличиваем контрастность (бинаризация)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

        # Распознаем только цифры и точки
        config = '--psm 6 -c tessedit_char_whitelist=0123456789.$'
        text = pytesseract.image_to_string(thresh, config=config)

        # Очищаем текст от мусора
        cleaned_text = ''.join(c for c in text if c.isdigit() or c == '.')
        try:
            return float(cleaned_text) if cleaned_text else 0.0
        except ValueError:
            return 0.0

    def save_debug_image(self, img, filename="debug_zone.png"):
        """Вспомогательная функция, чтобы проверить, правильную ли зону мы сканируем."""
        cv2.imwrite(filename, img)


# Проверочный запуск сканера
if __name__ == "__main__":
    vision = PokerVision()
    print("Тестируем захват экрана...")

    # Пример: сканируем прямоугольник в центре экрана (x=500, y=500, ширина=200, высота=50)
    test_crop = vision.capture_zone(500, 500, 200, 50)
    vision.save_debug_image(test_crop, "test_capture.png")

    print("Скриншот зоны сохранен в 'test_capture.png'. Проверь, попали ли нужные цифры!")