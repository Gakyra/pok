import asyncio
import json
import threading
import websockets

CONNECTED_CLIENTS = {}


class PokerServerThread(threading.Thread):

  def __init__(self, host="0.0.0.0", port=8765, app_instance=None):
    super().__init__(daemon=True)
    self.host = host
    self.port = port
    self.app = app_instance

  def run(self):
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()
    start_server = websockets.serve(self.handler, self.host, self.port)
    loop.run_until_complete(start_server)
    loop.run_forever()

  async def handler(self, websocket, path):
    player_id = None
    try:
      async for message in websocket:
        data = json.loads(message)

        if data.get("action") == "register":
          player_id = data.get("player_id")  # "P2" или "P3"
          CONNECTED_CLIENTS[player_id] = websocket
          print(f"[СЕТЬ] Подключен игрок: {player_id}")

        elif data.get("action") == "send_cards":
          pid = data.get("player_id")
          c1, c2 = data.get("card1"), data.get("card2")
          if self.app:
            # Передаем карты в главный поток Tkinter
            self.app.root.after(0, self.app.apply_network_cards, pid, c1, c2)

    except websockets.exceptions.ConnectionClosed:
      pass
    finally:
      if player_id in CONNECTED_CLIENTS:
        del CONNECTED_CLIENTS[player_id]


def send_signal_to_player(player_id, command_text):
  """Отправка приказа конкретному напарнику."""

  async def _send():
    if player_id in CONNECTED_CLIENTS:
      try:
        await CONNECTED_CLIENTS[player_id].send(
            json.dumps(
                {"action": "role_assignment", "command": command_text}
            )
        )
      except Exception as e:
        print(f"Ошибка отправки {player_id}: {e}")

  loop = asyncio.new_event_loop()
  loop.run_until_complete(_send())