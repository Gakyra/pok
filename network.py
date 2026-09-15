import asyncio
import json
import threading
import websockets

# Словарь подключенных клиентов: {'P2': websocket, 'P3': websocket}
CONNECTED_CLIENTS = {}


class PokerServerThread(threading.Thread):

  def __init__(self, host="0.0.0.0", port=8765, app_instance=None):
    super().__init__(daemon=True)
    self.host = host
    self.port = port
    self.app = app_instance
    self.loop = None

  def run(self):
    self.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(self.loop)
    start_server = websockets.serve(self.handler, self.host, self.port)
    self.loop.run_until_complete(start_server)
    print(f"[СЕТЬ] Сервер запущен на {self.host}:{self.port}")
    self.loop.run_forever()

  async def handler(self, websocket, path):
    player_id = None
    try:
      async for message in websocket:
        data = json.loads(message)

        # 1. Регистрация игрока (P2 или P3)
        if data.get("action") == "register":
          player_id = data.get("player_id")
          CONNECTED_CLIENTS[player_id] = websocket
          print(f"[СЕТЬ] Игрок {player_id} успешно подключен")

        # 2. Получение карт от напарника
        elif data.get("action") == "send_cards":
          pid = data.get("player_id")
          c1, c2 = data.get("card1"), data.get("card2")

          # Безопасная передача карт в главный поток Tkinter UI
          if self.app:
            self.app.root.after(0, self.app.apply_network_cards, pid, c1, c2)

    except websockets.exceptions.ConnectionClosed:
      pass
    finally:
      if player_id in CONNECTED_CLIENTS:
        del CONNECTED_CLIENTS[player_id]
        print(f"[СЕТЬ] Игрок {player_id} отключился")


def send_signal_to_player(server_instance, player_id, command_text):
  """Безопасная отправка сигнала из главного потока Tkinter в поток WebSockets."""
  if not server_instance or not server_instance.loop:
    return

  async def _send():
    if player_id in CONNECTED_CLIENTS:
      try:
        await CONNECTED_CLIENTS[player_id].send(
            json.dumps(
                {"action": "role_assignment", "command": command_text}
            )
        )
      except Exception as e:
        print(f"[ОШИБКА СЕТИ] Не удалось отправить команду {player_id}: {e}")

  # Запускаем корутину в цикле событий сетевого потока
  asyncio.run_coroutine_threadsafe(_send(), server_instance.loop)