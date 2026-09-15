import tkinter as tk
from tkinter import messagebox
import threading
import random
import json
import os
import math
import itertools
from datetime import datetime
from treys import Card, Evaluator, Deck

evaluator = Evaluator()

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poker_session_history.json")
CSV_EXPORT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poker_session_export.csv")

# =========================================================================
#  КОНФИГ: все настраиваемые числа в одном месте
# =========================================================================
CONFIG = {
    "exact_scenario_cap": 150000,   # выше -> точнее, но медленнее
    "monte_carlo_sims": 50000,      # прогонов, когда точный перебор невозможен
    "role_aggressor_mult": 1.4,     # x от справедливой доли -> роль "Агрессор"
    "role_shield_mult": 0.7,        # x от справедливой доли -> роль "Щит"
    "history_limit_shown": 40,      # сколько последних раздач показывать в истории
}

# =========================================================================
#  RANGE ANALYZER: таблица силы 169 стартовых рук (формула Чена)
# =========================================================================
RANK_ORDER = "23456789TJQKA"
RANK_VALUE = {c: i + 2 for i, c in enumerate(RANK_ORDER)}
SUITS = ['s', 'h', 'd', 'c']


def _chen_high_points(v):
    table = {14: 10, 13: 8, 12: 7, 11: 6, 10: 5}
    return table.get(v, v / 2.0)


def _chen_score(v1, v2, suited):
    hi, lo = max(v1, v2), min(v1, v2)
    if hi == lo:
        return max(_chen_high_points(hi) * 2, 5)
    score = _chen_high_points(hi)
    if suited:
        score += 2
    gap = hi - lo - 1
    if gap == 1:
        score -= 1
    elif gap == 2:
        score -= 2
    elif gap == 3:
        score -= 4
    elif gap >= 4:
        score -= 5
    if gap <= 1 and hi <= 12:
        score += 1
    return round(score * 2) / 2


def _build_range_table():
    types = []
    for i, r1c in enumerate(RANK_ORDER):
        for j, r2c in enumerate(RANK_ORDER):
            v1, v2 = RANK_VALUE[r1c], RANK_VALUE[r2c]
            if i == j:
                types.append((v1, v1, None))
            elif i < j:
                types.append((v2, v1, True))
                types.append((v2, v1, False))
    seen, uniq = set(), []
    for t in types:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    uniq.sort(key=lambda t: _chen_score(t[0], t[1], t[2]), reverse=True)
    return uniq


RANGE_TABLE = _build_range_table()

# Стиль оппонента -> % диапазона рук, которые он играет (топ X% по силе)
STYLE_RANGE_MAP = {"unknown": 100, "tight": 16, "loose": 55}
STYLE_ORDER = ["unknown", "tight", "loose"]
STYLE_LABELS = {"unknown": "❔ НЕИЗВЕСТНО", "tight": "🔒 ТАЙТ", "loose": "🌊 ЛУЗ"}
STYLE_COLORS = {"unknown": "#546e7a", "tight": "#c62828", "loose": "#ef6c00"}
STYLE_DESC = {
    "unknown": "диапазон не сужен — играем от 100% случайных рук",
    "tight": "играет редко, но сильно — диапазон сужен до топ ~16% рук",
    "loose": "играет часто и широко — диапазон сужен до топ ~55% рук",
}


def get_range_types(pct):
    n = max(1, round(len(RANGE_TABLE) * pct / 100.0))
    return RANGE_TABLE[:n]


def parse_range_token(token):
    """Разбирает один токен диапазона вида 'AA', 'AKs', 'KQo', '22+', 'A2s+'.
    Возвращает set из (hi, lo, suited) типов рук. Диапазоны через дефис
    (например 'A2s-A5s') не поддерживаются — используй '+' нотацию."""
    token = token.strip().upper()
    if not token:
        return set()
    plus = token.endswith("+")
    if plus:
        token = token[:-1]

    suited = None
    if token.endswith("S"):
        suited, token = True, token[:-1]
    elif token.endswith("O"):
        suited, token = False, token[:-1]

    if len(token) != 2 or token[0] not in RANK_VALUE or token[1] not in RANK_VALUE:
        return set()

    v1, v2 = RANK_VALUE[token[0]], RANK_VALUE[token[1]]
    result = set()

    if v1 == v2:  # пара, например "22+"
        lo_v = v1
        rng = range(lo_v, 15) if plus else [lo_v]
        for v in rng:
            result.add((v, v, None))
        return result

    hi, lo = max(v1, v2), min(v1, v2)
    suited_options = [True, False] if suited is None else [suited]
    if plus:
        for lo_v in range(lo, hi):  # до коннектора включительно
            for s in suited_options:
                result.add((hi, lo_v, s))
    else:
        for s in suited_options:
            result.add((hi, lo, s))
    return result


def parse_range_string(s):
    """'22+, A2s+, KQo, 76s' -> set типов рук. Пустая строка -> пустой set."""
    types = set()
    for tok in s.split(","):
        types |= parse_range_token(tok)
    return types


def build_combo_pool(hand_types, excluded_cards):
    pool = []
    for (hi, lo, suited) in hand_types:
        hi_c, lo_c = RANK_ORDER[hi - 2], RANK_ORDER[lo - 2]
        if suited is None:
            for a in range(4):
                for b in range(a + 1, 4):
                    c1 = Card.new(f"{hi_c}{SUITS[a]}")
                    c2 = Card.new(f"{hi_c}{SUITS[b]}")
                    if c1 in excluded_cards or c2 in excluded_cards:
                        continue
                    pool.append((c1, c2))
        elif suited:
            for s in SUITS:
                c1 = Card.new(f"{hi_c}{s}")
                c2 = Card.new(f"{lo_c}{s}")
                if c1 in excluded_cards or c2 in excluded_cards:
                    continue
                pool.append((c1, c2))
        else:
            for a in SUITS:
                for b in SUITS:
                    if a == b:
                        continue
                    c1 = Card.new(f"{hi_c}{a}")
                    c2 = Card.new(f"{lo_c}{b}")
                    if c1 in excluded_cards or c2 in excluded_cards:
                        continue
                    pool.append((c1, c2))
    return pool


def draw_from_pool(pool, available_set):
    if pool:
        for _ in range(40):
            c1, c2 = pool[random.randrange(len(pool))]
            if c1 in available_set and c2 in available_set:
                return c1, c2
    cards = random.sample(list(available_set), 2)
    return cards[0], cards[1]


# =========================================================================
#  ТОЧНЫЙ ПЕРЕБОР: если сценариев разумно мало — считаем без единой
#  случайности. Иначе откат на Monte Carlo (помечается честно).
# =========================================================================
def _comb(n, k):
    if n < k or k < 0:
        return 0
    return math.comb(n, k)


def try_exact_equity(active_team, active_opps, opp_pools, base_remaining, known_board):
    needed_board = 5 - len(known_board)
    estimate = _comb(len(base_remaining), needed_board)
    for pool in opp_pools:
        pool_size = len(pool) if pool is not None else _comb(len(base_remaining), 2)
        estimate *= max(pool_size, 1)
        if estimate > CONFIG["exact_scenario_cap"]:
            return None
    if estimate == 0:
        return None

    wins = [0] * (len(active_team) + len(active_opps))
    total = 0

    def recurse(opp_idx, available, opp_hands):
        nonlocal total
        if opp_idx == len(opp_pools):
            for board_extra in itertools.combinations(sorted(available), needed_board):
                current_board = known_board + list(board_extra)
                best_score, winner_idx = float('inf'), -1
                for idx, p in enumerate(active_team):
                    score = evaluator.evaluate(p["cards"], current_board)
                    if score < best_score:
                        best_score, winner_idx = score, idx
                for o_idx, hand in enumerate(opp_hands):
                    score = evaluator.evaluate(hand, current_board)
                    if score < best_score:
                        best_score, winner_idx = score, len(active_team) + o_idx
                wins[winner_idx] += 1
                total += 1
            return
        pool = opp_pools[opp_idx]
        candidates = pool if pool is not None else list(itertools.combinations(sorted(available), 2))
        for c1, c2 in candidates:
            if c1 not in available or c2 not in available:
                continue
            recurse(opp_idx + 1, available - {c1, c2}, opp_hands + [[c1, c2]])

    recurse(0, set(base_remaining), [])
    if total == 0:
        return None
    return wins, total


class PokerApp:
    def __init__(self, root):
        self.root = root
        self.root.withdraw()
        self.root.title("Покерный Тактический ИИ PRO")
        self.root.configure(bg="#121212")

        self.bg_dark = "#121212"
        self.card_bg = "#2d2d2d"
        self.accent_green = "#2e7d32"
        self.accent_red = "#c62828"
        self.panel_team_bg = "#0f1f13"
        self.panel_enemy_bg = "#1f1010"

        self.players_data = []
        self.board_cards = []
        self.selected_target = "p0"
        self.player_rows = []
        self.board_card_labels = []
        self.deck_buttons = {}
        self.deck_visible = True

        self.session_history = self.load_history()
        self.equity_cache = {}
        self.street_trend = {}  # {player_name: [(этап, эквити), ...]} за текущую раздачу

        self.run_setup_dialog()

        self.create_widgets()
        self.rebuild_players_list()
        self.update_selection_visual()

    # ---------------------------------------------------------------
    #  СТАРТОВЫЙ ДИАЛОГ: сколько игроков, сколько наша команда, докинг окна
    # ---------------------------------------------------------------
    def run_setup_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Настройка стола")
        dialog.configure(bg=self.bg_dark)
        dialog.geometry("460x540")
        dialog.resizable(False, False)
        dialog.grab_set()

        result = {}

        tk.Label(dialog, text="♠ НОВАЯ РАЗДАЧА", bg=self.bg_dark, fg="#00e676",
                 font=("Arial", 18, "bold")).pack(pady=(24, 14))

        tk.Label(dialog, text="Сколько игроков за столом всего?", bg=self.bg_dark, fg="white",
                 font=("Arial", 10)).pack(pady=(6, 4))
        total_var = tk.IntVar(value=4)
        tk.Spinbox(dialog, from_=2, to=9, textvariable=total_var, width=5, font=("Arial", 14, "bold"),
                   justify="center").pack()

        tk.Label(dialog, text="Сколько из них ваша команда?", bg=self.bg_dark, fg="white",
                 font=("Arial", 10)).pack(pady=(16, 4))
        team_var = tk.IntVar(value=2)
        tk.Spinbox(dialog, from_=1, to=8, textvariable=team_var, width=5, font=("Arial", 14, "bold"),
                   justify="center").pack()

        tk.Label(dialog, text="Куда пристроить окно рядом с браузером?", bg=self.bg_dark, fg="white",
                 font=("Arial", 10)).pack(pady=(18, 6))
        dock_var = tk.StringVar(value="right")
        dock_frame = tk.Frame(dialog, bg=self.bg_dark)
        dock_frame.pack()
        for val, label in [("left", "⬅ Слева"), ("right", "Справа ➡"), ("full", "Весь экран")]:
            tk.Radiobutton(dock_frame, text=label, variable=dock_var, value=val, bg=self.bg_dark, fg="white",
                          selectcolor="#2d2d2d", activebackground=self.bg_dark, activeforeground="white",
                          font=("Arial", 10)).pack(side=tk.LEFT, padx=8)

        tk.Label(dialog, text="Программа займёт свою половину экрана автоматически.\n"
                              "Браузер с покером открой на ДРУГУЮ половину сам:\n"
                              "Windows — перетащи окно браузера к краю экрана (или Win+стрелка),\n"
                              "macOS — зажми зелёную кнопку в углу окна и выбери 'Split View'.\n"
                              "Кнопки докинга останутся вверху программы — можно менять в любой момент.",
                bg=self.bg_dark, fg="#757575", font=("Arial", 8), justify="left").pack(pady=(10, 0), padx=20)

        def confirm():
            result['total'] = total_var.get()
            result['team'] = min(team_var.get(), result['total'])
            result['dock'] = dock_var.get()
            dialog.destroy()

        tk.Button(dialog, text="▶  НАЧАТЬ", bg="#00c853", fg="black", font=("Arial", 13, "bold"),
                 command=confirm).pack(pady=30, ipadx=24, ipady=8)

        dialog.protocol("WM_DELETE_WINDOW", confirm)
        self.root.wait_window(dialog)

        total = result.get('total', 4)
        team_n = result.get('team', 2)
        dock = result.get('dock', 'right')

        self.players_data = []
        for i in range(total):
            if i < team_n:
                name = "Вы" if i == 0 else f"Напарник {i}"
                self.players_data.append({"name": name, "is_team": True, "active": True, "cards": [], "equity": 0.0})
            else:
                self.players_data.append({
                    "name": f"Враг {i - team_n + 1}", "is_team": False, "active": True, "cards": [],
                    "equity": 0.0, "style": "unknown",
                })

        self.apply_window_dock(dock)
        self.root.deiconify()

    def apply_window_dock(self, dock):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if dock == "left":
            w = sw // 2
            self.root.geometry(f"{w}x{sh}+0+0")
        elif dock == "right":
            w = sw // 2
            self.root.geometry(f"{w}x{sh}+{sw - w}+0")
        else:
            self.root.geometry(f"{sw}x{sh}+0+0")

    # ---------------------------------------------------------------
    #  ИСТОРИЯ СЕССИИ
    # ---------------------------------------------------------------
    def load_history(self):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_history(self):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.session_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Не удалось сохранить историю:", e)

    def export_csv(self):
        if not self.session_history:
            messagebox.showinfo("Экспорт", "История пуста — пока нечего экспортировать.")
            return
        import csv
        all_names = sorted({name for rec in self.session_history for name in rec.get("results", {})})
        try:
            with open(CSV_EXPORT_FILE, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "mode"] + all_names)
                for rec in self.session_history:
                    row = [rec.get("timestamp", ""), rec.get("mode", "")]
                    row += [f"{rec['results'].get(n, ''):.1f}" if n in rec.get("results", {}) else "" for n in all_names]
                    writer.writerow(row)
            messagebox.showinfo("Экспорт", f"Сохранено:\n{CSV_EXPORT_FILE}")
        except Exception as e:
            messagebox.showerror("Ошибка экспорта", str(e))

    def show_session_history(self):
        win = tk.Toplevel(self.root)
        win.title("История прогнозов сессии")
        win.geometry("560x480")
        win.configure(bg=self.bg_dark)
        txt = tk.Text(win, bg="#121212", fg="#00e676", font=("Courier", 10), wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        if not self.session_history:
            txt.insert(tk.END, "Пока нет ни одного расчёта в этой сессии.")
        else:
            totals = {}
            lines = []
            for rec in self.session_history[-40:]:
                lines.append(f"[{rec.get('timestamp','?')}] режим: {rec.get('mode','?')}")
                for name, eq in rec.get("results", {}).items():
                    lines.append(f"   {name}: {eq:.1f}%")
                    totals.setdefault(name, []).append(eq)
                lines.append("")
            summary = ["=" * 46, "СРЕДНЯЯ ЭКВИТИ ПО ИГРОКАМ ЗА СЕССИЮ:", "=" * 46]
            for name, vals in totals.items():
                summary.append(f" {name}: среднее {sum(vals)/len(vals):.1f}% за {len(vals)} раздач(и)")
            txt.insert(tk.END, "\n".join(summary) + "\n\n" + "\n".join(lines))
        txt.config(state=tk.DISABLED)

    # ---------------------------------------------------------------
    #  UI
    # ---------------------------------------------------------------
    def create_widgets(self):
        header = tk.Frame(self.root, bg="#0a0a0a", height=46)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)
        tk.Label(header, text="♠ ТАКТИЧЕСКИЙ ШТАБ", bg="#0a0a0a", fg="#00e676",
                 font=("Arial", 14, "bold")).pack(side=tk.LEFT, padx=14, pady=8)

        dock_box = tk.Frame(header, bg="#0a0a0a")
        dock_box.pack(side=tk.LEFT, padx=16)
        tk.Label(dock_box, text="Окно:", bg="#0a0a0a", fg="#757575", font=("Arial", 8)).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(dock_box, text="⬅", bg="#263238", fg="white", font=("Arial", 9, "bold"), width=3,
                 command=lambda: self.apply_window_dock("left")).pack(side=tk.LEFT, padx=1)
        tk.Button(dock_box, text="▢", bg="#263238", fg="white", font=("Arial", 9, "bold"), width=3,
                 command=lambda: self.apply_window_dock("full")).pack(side=tk.LEFT, padx=1)
        tk.Button(dock_box, text="➡", bg="#263238", fg="white", font=("Arial", 9, "bold"), width=3,
                 command=lambda: self.apply_window_dock("right")).pack(side=tk.LEFT, padx=1)

        tk.Button(header, text="📊 История", bg="#0a0a0a", fg="#757575", relief=tk.FLAT,
                 font=("Arial", 9), command=self.show_session_history).pack(side=tk.RIGHT, padx=(4, 14))
        tk.Button(header, text="⬇ CSV", bg="#0a0a0a", fg="#757575", relief=tk.FLAT,
                 font=("Arial", 9), command=self.export_csv).pack(side=tk.RIGHT, padx=4)
        tk.Frame(self.root, bg="#00e676", height=2).pack(fill=tk.X, side=tk.TOP)

        # Скроллируемая область на случай нехватки высоты
        outer = tk.Frame(self.root, bg=self.bg_dark)
        outer.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(outer, bg=self.bg_dark, highlightthickness=0)
        vscroll = tk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        self.scroll_frame = tk.Frame(canvas, bg=self.bg_dark)
        self.scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        root_c = self.scroll_frame

        # --- СТОЛ ---
        board_frame = tk.LabelFrame(root_c, text=" КАРТЫ НА СТОЛЕ ", bg=self.bg_dark, fg="#00e676",
                                    font=("Arial", 10, "bold"))
        board_frame.pack(fill=tk.X, pady=(8, 4), padx=8)
        board_row = tk.Frame(board_frame, bg=self.bg_dark)
        board_row.pack(pady=8)
        self.btn_select_board = tk.Button(board_row, text="СТОЛ", bg="#424242", fg="white",
                                          font=("Arial", 9, "bold"), command=lambda: self.set_target("board"))
        self.btn_select_board.pack(side=tk.LEFT, padx=8)
        for i in range(5):
            lbl = tk.Label(board_row, text="—", bg=self.card_bg, fg="#888888", width=4, height=2,
                           relief=tk.GROOVE, font=("Arial", 10, "bold"))
            lbl.pack(side=tk.LEFT, padx=3)
            self.board_card_labels.append(lbl)

        # --- КОЛОДА (сворачиваемая) ---
        deck_header = tk.Frame(root_c, bg=self.bg_dark)
        deck_header.pack(fill=tk.X, padx=8)
        self.btn_toggle_deck = tk.Button(deck_header, text="▼ КОЛОДА (кликни карту)", bg="#1a1a1a", fg="#29b6f6",
                                         font=("Arial", 9, "bold"), relief=tk.FLAT, anchor="w",
                                         command=self.toggle_deck)
        self.btn_toggle_deck.pack(fill=tk.X)

        self.deck_frame = tk.Frame(root_c, bg=self.bg_dark)
        self.deck_frame.pack(fill=tk.X, padx=8, pady=(2, 6))

        suits_symbols = {'s': '♠', 'h': '♥', 'd': '♦', 'c': '♣'}
        suits_colors = {'s': 'black', 'h': 'red', 'd': 'blue', 'c': 'green'}
        ranks = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']

        for suit in ['s', 'h', 'd', 'c']:
            row_frame = tk.Frame(self.deck_frame, bg=self.bg_dark)
            row_frame.pack(fill=tk.X, pady=1)
            tk.Label(row_frame, text=suits_symbols[suit], fg=suits_colors[suit], bg=self.bg_dark,
                    font=("Arial", 12, "bold"), width=2).pack(side=tk.LEFT, padx=2)
            for rank in ranks:
                card_str = f"{rank}{suit}"
                card_obj = Card.new(card_str)
                btn = tk.Button(row_frame, text=rank, bg="white", fg=suits_colors[suit], font=("Arial", 8, "bold"),
                               width=2, height=1, command=lambda c=card_obj, cs=card_str: self.add_card_to_target(c, cs))
                btn.pack(side=tk.LEFT, padx=1, pady=1)
                self.deck_buttons[card_str] = btn

        # --- КНОПКА РАСЧЁТА ---
        action_row = tk.Frame(root_c, bg=self.bg_dark)
        action_row.pack(fill=tk.X, padx=8, pady=6)
        tk.Button(action_row, text="⚡ РАССЧИТАТЬ", bg="#00c853", fg="black", font=("Arial", 13, "bold"),
                 height=1, command=self.run_simulation).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        tk.Button(action_row, text="СБРОС", bg="#d50000", fg="white", font=("Arial", 10, "bold"),
                 command=self.reset_game).pack(side=tk.LEFT, padx=(4, 0))

        # --- ИГРОКИ: две колонки ---
        players_row = tk.Frame(root_c, bg=self.bg_dark)
        players_row.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.team_container = tk.LabelFrame(players_row, text=" 🟢 НАША КОМАНДА ", bg=self.panel_team_bg,
                                            fg="#69f0ae", font=("Arial", 10, "bold"))
        self.team_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        tk.Button(self.team_container, text="+ Добавить союзника", bg="#1b5e20", fg="white",
                 font=("Arial", 8, "bold"), command=self.add_team_player).pack(fill=tk.X, padx=4, pady=(4, 2))

        self.enemy_container = tk.LabelFrame(players_row, text=" 🔴 ВРАГИ ", bg=self.panel_enemy_bg,
                                             fg="#ff8a80", font=("Arial", 10, "bold"))
        self.enemy_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))
        tk.Button(self.enemy_container, text="+ Добавить врага", bg="#7f1010", fg="white",
                 font=("Arial", 8, "bold"), command=self.add_enemy_player).pack(fill=tk.X, padx=4, pady=(4, 2))

        # --- ГРАФИК ЭКВИТИ ---
        chart_frame = tk.LabelFrame(root_c, text=" ЭКВИТИ ", bg=self.bg_dark, fg="#29b6f6", font=("Arial", 9, "bold"))
        chart_frame.pack(fill=tk.X, padx=8, pady=4)
        self.equity_canvas = tk.Canvas(chart_frame, bg="#0d0d0d", height=120, highlightthickness=0)
        self.equity_canvas.pack(fill=tk.X, padx=4, pady=4)

        # --- РЕЗУЛЬТАТЫ ---
        results_frame = tk.LabelFrame(root_c, text=" ПЛАН ДЕЙСТВИЙ ", bg=self.bg_dark, fg="#00e676",
                                      font=("Arial", 10, "bold"))
        results_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 10))
        self.txt_analysis = tk.Text(results_frame, bg="#121212", fg="#00ff00", font=("Courier", 9), wrap=tk.WORD,
                                    state=tk.DISABLED, height=14)
        self.txt_analysis.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def toggle_deck(self):
        self.deck_visible = not self.deck_visible
        if self.deck_visible:
            self.deck_frame.pack(fill=tk.X, padx=8, pady=(2, 6))
            self.btn_toggle_deck.config(text="▼ КОЛОДА (кликни карту)")
        else:
            self.deck_frame.pack_forget()
            self.btn_toggle_deck.config(text="▶ КОЛОДА (скрыта, кликни чтобы открыть)")

    # ---------------------------------------------------------------
    #  СПИСОК ИГРОКОВ (две колонки, компактные строки)
    # ---------------------------------------------------------------
    def rebuild_players_list(self):
        for row in self.player_rows:
            row["frame"].destroy()
        self.player_rows.clear()

        for i, p in enumerate(self.players_data):
            container = self.team_container if p["is_team"] else self.enemy_container
            p_row_frame = tk.Frame(container, bg=container.cget("bg"), pady=3)
            p_row_frame.pack(fill=tk.X, padx=4)

            line1 = tk.Frame(p_row_frame, bg=container.cget("bg"))
            line1.pack(fill=tk.X)

            name_var = tk.StringVar(value=p["name"])
            name_entry = tk.Entry(line1, textvariable=name_var, font=("Arial", 9, "bold"), width=10,
                                  bg="#2d2d2d", fg="white", insertbackground="white")
            name_entry.pack(side=tk.LEFT, padx=2)
            name_var.trace_add("write", lambda *a, idx=i, var=name_var: self.update_player_name(idx, var))

            active_text = "В игре" if p["active"] else "Пас"
            active_color = self.accent_green if p["active"] else self.accent_red
            btn_active = tk.Button(line1, text=active_text, bg=active_color, fg="white", font=("Arial", 7, "bold"),
                                   width=6, command=lambda idx=i: self.toggle_active(idx))
            btn_active.pack(side=tk.LEFT, padx=2)

            btn_delete = tk.Button(line1, text="✖ Удалить", bg="#37474f", fg="white", font=("Arial", 7, "bold"),
                                   command=lambda idx=i: self.delete_player(idx))
            btn_delete.pack(side=tk.RIGHT, padx=2)

            btn_focus, lbl1, lbl2, style_btn, btn_clear_cards = None, None, None, None, None

            if p["is_team"]:
                btn_focus = tk.Button(line1, text="🎴", font=("Arial", 9, "bold"), bg="#424242", fg="white", width=3,
                                      command=lambda idx=i: self.set_target(f"p{idx}"))
                btn_focus.pack(side=tk.LEFT, padx=2)
                lbl1 = tk.Label(line1, text="--", bg=self.card_bg, fg="white", width=3, font=("Arial", 9, "bold"))
                lbl1.pack(side=tk.LEFT, padx=1)
                lbl2 = tk.Label(line1, text="--", bg=self.card_bg, fg="white", width=3, font=("Arial", 9, "bold"))
                lbl2.pack(side=tk.LEFT, padx=1)
                btn_clear_cards = tk.Button(line1, text="🗑", font=("Arial", 9, "bold"), bg="#5d1010", fg="white",
                                            width=3, command=lambda idx=i: self.clear_player_cards(idx))
                btn_clear_cards.pack(side=tk.LEFT, padx=(4, 0))
            else:
                line2 = tk.Frame(p_row_frame, bg=container.cget("bg"))
                line2.pack(fill=tk.X, pady=(2, 0))
                style = p.get("style", "unknown")
                custom = p.get("custom_range_str")
                btn_text = f"⚙ {custom}" if custom else STYLE_LABELS[style]
                btn_bg = "#4527a0" if custom else STYLE_COLORS[style]
                style_btn = tk.Button(line2, text=btn_text, bg=btn_bg, fg="white",
                                      font=("Arial", 8, "bold"),
                                      command=lambda idx=i: self.cycle_style(idx))
                style_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 1))
                btn_range = tk.Button(line2, text="⚙", font=("Arial", 8, "bold"), bg="#37474f", fg="white", width=2,
                                      command=lambda idx=i: self.open_range_dialog(idx))
                btn_range.pack(side=tk.LEFT, padx=(1, 2))

            self.player_rows.append({
                "frame": p_row_frame, "name_entry": name_entry, "focus_btn": btn_focus,
                "lbl1": lbl1, "lbl2": lbl2, "active_btn": btn_active, "delete_btn": btn_delete,
                "style_btn": style_btn, "clear_cards_btn": btn_clear_cards,
            })

        self.update_cards_display()

    def add_team_player(self):
        n = sum(1 for p in self.players_data if p["is_team"])
        self.players_data.append({"name": f"Напарник {n}", "is_team": True, "active": True, "cards": [], "equity": 0.0})
        self.rebuild_players_list()

    def add_enemy_player(self):
        n = sum(1 for p in self.players_data if not p["is_team"])
        self.players_data.append({"name": f"Враг {n + 1}", "is_team": False, "active": True, "cards": [],
                                  "equity": 0.0, "style": "unknown"})
        self.rebuild_players_list()

    def clear_player_cards(self, idx):
        p = self.players_data[idx]
        for c in list(p["cards"]):
            self.remove_card_everywhere(c, card_to_input_str(c))
        self.set_target(f"p{idx}")

    def cycle_style(self, idx):
        p = self.players_data[idx]
        # Если был задан кастомный диапазон - сначала просто снимаем его,
        # возвращая контроль тумблеру, а не сразу переключаем стиль.
        if p.get("custom_range_str"):
            p["custom_range_str"] = None
            p["custom_range_types"] = None
        else:
            cur = p.get("style", "unknown")
            p["style"] = STYLE_ORDER[(STYLE_ORDER.index(cur) + 1) % len(STYLE_ORDER)]
        self.rebuild_players_list()

    def open_range_dialog(self, idx):
        """Ручной ввод диапазона врага в синтаксисе '22+, A2s+, KQo'.
        Предназначено для настройки МЕЖДУ раздачами, не во время хода —
        поэтому открывается отдельным окном, а не встроено в HUD."""
        p = self.players_data[idx]
        win = tk.Toplevel(self.root)
        win.title(f"Диапазон: {p['name']}")
        win.configure(bg=self.bg_dark)
        win.geometry("420x260")
        win.grab_set()

        tk.Label(win, text=f"Диапазон рук для {p['name']}", bg=self.bg_dark, fg="#00e676",
                font=("Arial", 12, "bold")).pack(pady=(16, 6))
        tk.Label(win, text="Синтаксис: 22+, A2s+, KQo, JTs (через запятую)\n"
                           "Оставь пустым, чтобы вернуться к тумблеру стиля.",
                bg=self.bg_dark, fg="#757575", font=("Arial", 8), justify="left").pack(pady=(0, 10), padx=16)

        entry = tk.Entry(win, font=("Arial", 11), bg="#2d2d2d", fg="white", insertbackground="white", width=36)
        entry.insert(0, p.get("custom_range_str") or "")
        entry.pack(pady=6, padx=16)

        preview_lbl = tk.Label(win, text="", bg=self.bg_dark, fg="#29b6f6", font=("Arial", 9), wraplength=380,
                               justify="left")
        preview_lbl.pack(pady=6, padx=16)

        def preview():
            types = parse_range_string(entry.get())
            preview_lbl.config(text=f"Распознано типов рук: {len(types)} из 169"
                                     if entry.get().strip() else "Диапазон будет очищен.")

        def save():
            raw = entry.get().strip()
            if not raw:
                p["custom_range_str"] = None
                p["custom_range_types"] = None
            else:
                types = parse_range_string(raw)
                if not types:
                    messagebox.showwarning("Ошибка", "Не удалось распознать ни одной руки — проверь синтаксис.")
                    return
                p["custom_range_str"] = raw
                p["custom_range_types"] = types
            win.destroy()
            self.rebuild_players_list()

        entry.bind("<KeyRelease>", lambda e: preview())
        preview()

        btn_row = tk.Frame(win, bg=self.bg_dark)
        btn_row.pack(pady=16)
        tk.Button(btn_row, text="Сохранить", bg="#00c853", fg="black", font=("Arial", 10, "bold"),
                 command=save).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Отмена", bg="#37474f", fg="white", font=("Arial", 10),
                 command=win.destroy).pack(side=tk.LEFT, padx=6)

    def update_player_name(self, idx, var):
        if idx < len(self.players_data):
            self.players_data[idx]["name"] = var.get()

    def toggle_active(self, idx):
        p = self.players_data[idx]
        p["active"] = not p["active"]
        row_ui = self.player_rows[idx]
        if p["active"]:
            row_ui["active_btn"].config(text="В игре", bg=self.accent_green)
        else:
            row_ui["active_btn"].config(text="Пас", bg=self.accent_red)

    def delete_player(self, idx):
        p = self.players_data[idx]
        for c in list(p["cards"]):
            self.remove_card_everywhere(c, card_to_input_str(c))
        self.players_data.pop(idx)
        self.rebuild_players_list()
        self.set_target("p0")

    # ---------------------------------------------------------------
    #  ВЫБОР КАРТ
    # ---------------------------------------------------------------
    def set_target(self, target):
        self.selected_target = target
        self.update_selection_visual()

    def update_selection_visual(self):
        for i, p in enumerate(self.players_data):
            row_ui = self.player_rows[i] if i < len(self.player_rows) else None
            if row_ui and p["is_team"] and row_ui["focus_btn"]:
                if self.selected_target == f"p{i}":
                    row_ui["focus_btn"].config(bg="#00b0ff", fg="black")
                else:
                    row_ui["focus_btn"].config(bg="#424242", fg="white")
        if self.selected_target == "board":
            self.btn_select_board.config(bg="#00b0ff", fg="black")
        else:
            self.btn_select_board.config(bg="#424242", fg="white")

    def add_card_to_target(self, card_obj, card_str):
        all_used = []
        for p in self.players_data:
            all_used.extend(p["cards"])
        all_used.extend(self.board_cards)

        if card_obj in all_used:
            self.remove_card_everywhere(card_obj, card_str)
            return

        if self.selected_target.startswith("p"):
            p_idx = int(self.selected_target[1:])
            if p_idx >= len(self.players_data):
                return
            p = self.players_data[p_idx]
            if not p["is_team"]:
                return
            if len(p["cards"]) < 2:
                p["cards"].append(card_obj)
                self.deck_buttons[card_str].config(bg="#757575", fg="white")
                self.update_cards_display()
                if len(p["cards"]) == 2:
                    found = False
                    for nxt in range(p_idx + 1, len(self.players_data)):
                        if self.players_data[nxt]["is_team"]:
                            self.set_target(f"p{nxt}")
                            found = True
                            break
                    if not found:
                        self.set_target("board")
            else:
                messagebox.showwarning("Лимит", f"У {p['name']} уже выбрано 2 карты!")
        elif self.selected_target == "board":
            if len(self.board_cards) < 5:
                self.board_cards.append(card_obj)
                self.deck_buttons[card_str].config(bg="#757575", fg="white")
                self.update_cards_display()
            else:
                messagebox.showwarning("Лимит", "На столе не может быть больше 5 карт!")

    def remove_card_everywhere(self, card_obj, card_str):
        for p in self.players_data:
            if card_obj in p["cards"]:
                p["cards"].remove(card_obj)
        if card_obj in self.board_cards:
            self.board_cards.remove(card_obj)
        self.deck_buttons[card_str].config(bg="white")
        colors = {'s': 'black', 'h': 'red', 'd': 'blue', 'c': 'green'}
        self.deck_buttons[card_str].config(fg=colors[card_str[1]])
        self.update_cards_display()

    def update_cards_display(self):
        for i, p in enumerate(self.players_data):
            if i < len(self.player_rows):
                row_ui = self.player_rows[i]
                if p["is_team"] and row_ui["lbl1"] and row_ui["lbl2"]:
                    for slot_idx in range(2):
                        lbl = row_ui["lbl1"] if slot_idx == 0 else row_ui["lbl2"]
                        if slot_idx < len(p["cards"]):
                            lbl.config(text=card_to_str(p["cards"][slot_idx]), bg="#4caf50", fg="white")
                        else:
                            lbl.config(text="--", bg=self.card_bg, fg="white")
        for i in range(5):
            if i < len(self.board_cards):
                self.board_card_labels[i].config(text=card_to_str(self.board_cards[i]), bg="#00b0ff", fg="white")
            else:
                self.board_card_labels[i].config(text="—", bg=self.card_bg, fg="#888888")

    def reset_game(self):
        for p in self.players_data:
            p["cards"] = []
            p["active"] = True
            p["equity"] = 0.0
        self.board_cards = []
        self.street_trend = {}
        colors = {'s': 'black', 'h': 'red', 'd': 'blue', 'c': 'green'}
        for card_str, btn in self.deck_buttons.items():
            btn.config(bg="white", fg=colors[card_str[1]])
        self.rebuild_players_list()
        self.set_target("p0")
        self.equity_canvas.delete("all")
        self.write_analysis("Карты сброшены. Готовы к новой раздаче!")

    def write_analysis(self, text):
        self.txt_analysis.config(state=tk.NORMAL)
        self.txt_analysis.delete(1.0, tk.END)
        self.txt_analysis.insert(tk.END, text)
        self.txt_analysis.config(state=tk.DISABLED)

    # ---------------------------------------------------------------
    #  РАСЧЁТ
    # ---------------------------------------------------------------
    def run_simulation(self):
        active_team = [p for p in self.players_data if p["is_team"] and p["active"]]
        active_opps = [p for p in self.players_data if not p["is_team"] and p["active"]]

        for p in active_team:
            if len(p["cards"]) != 2:
                messagebox.showerror("Ошибка", f"Заполни карты для активного игрока: {p['name']}!")
                return
        if not active_team:
            messagebox.showwarning("Внимание", "Все наши игроки сбросили карты!")
            return
        if not active_opps:
            self.write_analysis("🎉 ВСЕ ВРАГИ СБРОСИЛИ КАРТЫ!\nКоманда забирает банк без боя!")
            return

        self.write_analysis("Считаю...")
        thread = threading.Thread(target=self.calc_thread_target, args=(active_team, active_opps))
        thread.start()

    def _build_opponent_pools(self, active_opps, known_cards):
        """Строит пул возможных рук для каждого врага: либо по кастомному
        диапазону (если задан вручную через '⚙'), либо по тегу стиля."""
        opp_pools = []
        for opp in active_opps:
            custom = opp.get("custom_range_types")
            if custom:
                pool = build_combo_pool(custom, known_cards)
                opp_pools.append(pool if pool else None)
                continue
            pct = STYLE_RANGE_MAP.get(opp.get("style", "unknown"), 100)
            if pct >= 100:
                opp_pools.append(None)
            else:
                pool = build_combo_pool(get_range_types(pct), known_cards)
                opp_pools.append(pool if pool else None)
        return opp_pools

    def _run_monte_carlo(self, active_team, active_opps, opp_pools, base_remaining):
        sims = CONFIG["monte_carlo_sims"]
        wins = [0] * (len(active_team) + len(active_opps))
        for _ in range(sims):
            available = set(base_remaining)
            opp_hands = []
            for pool in opp_pools:
                c1, c2 = draw_from_pool(pool, available)
                available.discard(c1)
                available.discard(c2)
                opp_hands.append([c1, c2])
            current_board = list(self.board_cards)
            needed = 5 - len(current_board)
            if needed > 0:
                current_board.extend(random.sample(list(available), needed))
            best_score, winner_idx = float('inf'), -1
            for idx, p in enumerate(active_team):
                score = evaluator.evaluate(p["cards"], current_board)
                if score < best_score:
                    best_score, winner_idx = score, idx
            for o_idx, hand in enumerate(opp_hands):
                score = evaluator.evaluate(hand, current_board)
                if score < best_score:
                    best_score, winner_idx = score, len(active_team) + o_idx
            wins[winner_idx] += 1
        mode_label = (f"ОЦЕНКА Monte Carlo — {sims:,} сценариев "
                      f"(точный перебор невозможен: слишком широкие диапазоны)")
        return wins, sims, mode_label

    def _make_cache_key(self, active_team, active_opps):
        return (
            tuple(tuple(sorted(p["cards"])) for p in active_team),
            tuple(sorted(self.board_cards)),
            tuple(opp.get("custom_range_str") or opp.get("style", "unknown") for opp in active_opps),
        )

    def _current_stage_label(self):
        n = len(self.board_cards)
        return {0: "Префлоп", 3: "Флоп", 4: "Тёрн", 5: "Ривер"}.get(n, f"{n} карт")

    def _record_street_trend(self, active_team, active_opps):
        stage = self._current_stage_label()
        for p in active_team + active_opps:
            hist = self.street_trend.setdefault(p["name"], [])
            if not hist or hist[-1][0] != stage:
                hist.append((stage, p["equity"]))
            else:
                hist[-1] = (stage, p["equity"])

    def calc_thread_target(self, active_team, active_opps):
        known_cards = set()
        for p in self.players_data:
            known_cards.update(p["cards"])
        known_cards.update(self.board_cards)

        cache_key = self._make_cache_key(active_team, active_opps)
        cached = self.equity_cache.get(cache_key)

        if cached is not None:
            wins, total, mode_label = cached
            mode_label += " (из кэша, уже считали этот расклад)"
        else:
            full_deck = Deck.GetFullDeck()
            base_remaining = [c for c in full_deck if c not in known_cards]
            opp_pools = self._build_opponent_pools(active_opps, known_cards)

            exact_result = try_exact_equity(active_team, active_opps, opp_pools, base_remaining,
                                            list(self.board_cards))
            if exact_result is not None:
                wins, total = exact_result
                mode_label = f"ТОЧНЫЙ РАСЧЁТ — все {total:,} сценария(ев) без исключений, 0% погрешности"
            else:
                wins, total, mode_label = self._run_monte_carlo(active_team, active_opps, opp_pools, base_remaining)

            self.equity_cache[cache_key] = (wins, total, mode_label)

        for idx, p in enumerate(active_team):
            p["equity"] = (wins[idx] / total) * 100
        for o_idx, opp in enumerate(active_opps):
            opp["equity"] = (wins[len(active_team) + o_idx] / total) * 100

        self._record_street_trend(active_team, active_opps)
        self.root.after(0, lambda: self.show_tactical_results(active_team, active_opps, mode_label))

    def draw_equity_chart(self, active_team, active_opps):
        self.equity_canvas.delete("all")
        self.equity_canvas.update_idletasks()
        width = max(self.equity_canvas.winfo_width(), 300)
        height = 120
        all_players = [(p["name"], p["equity"], True) for p in active_team] + \
                      [(p["name"], p["equity"], False) for p in active_opps]
        if not all_players:
            return
        n = len(all_players)
        bar_w = max(24, (width - 20) // n - 8)
        max_eq = max(1.0, max(eq for _, eq, _ in all_players))
        x = 10
        for name, eq, is_team in all_players:
            bar_h = int((eq / max_eq) * (height - 36))
            color = self.accent_green if is_team else self.accent_red
            y0 = height - 22
            y1 = y0 - bar_h
            self.equity_canvas.create_rectangle(x, y1, x + bar_w, y0, fill=color, outline="")
            self.equity_canvas.create_text(x + bar_w / 2, y1 - 8, text=f"{eq:.0f}%", fill="white",
                                           font=("Arial", 8, "bold"))
            short = (name[:6] + "…") if len(name) > 7 else name
            self.equity_canvas.create_text(x + bar_w / 2, y0 + 9, text=short, fill="#aaaaaa", font=("Arial", 7))
            x += bar_w + 8

    def _assign_role(self, p, leader, fair_share):
        eq = p["equity"]
        edge = eq - fair_share
        if p is leader and eq >= fair_share * CONFIG["role_aggressor_mult"]:
            role, action = "🔥 АГРЕССОР", "Рейзь/бет — тяни банк на себя, не коллируй пассивно."
        elif eq >= fair_share * CONFIG["role_shield_mult"]:
            role, action = "🛡️ ЩИТ", f"Коллируй, прикрывай {leader['name']}, защищай банк."
        else:
            role, action = "🃏 НАБЛЮДАТЕЛЬ/ПРИМАНКА", "Играй по минимуму, на крупную ставку — думай о фолде."
        return role, action, edge

    def _format_trend(self, name):
        hist = self.street_trend.get(name, [])
        if len(hist) < 2:
            return None
        return " → ".join(f"{stage} {eq:.0f}%" for stage, eq in hist)

    def show_tactical_results(self, active_team, active_opps, mode_label=""):
        total_team_eq = sum(p["equity"] for p in active_team)
        total_opp_eq = sum(opp["equity"] for opp in active_opps)
        leader = max(active_team, key=lambda x: x["equity"])

        # Справедливая доля банка при случайном раскладе — база для ролей,
        # чтобы пороги не зависели от того, сколько игроков сидит за столом.
        n_active = len(active_team) + len(active_opps)
        fair_share = 100.0 / n_active if n_active else 0.0

        out = []
        out.append("=" * 50)
        out.append(f"КОМАНДА: {total_team_eq:.1f}%   ВРАГИ: {total_opp_eq:.1f}%")
        out.append(f"Справедливая доля при {n_active} игроках: {fair_share:.1f}%")
        out.append(f"[{mode_label}]")
        out.append("=" * 50)

        for p in active_team:
            role, action, edge = self._assign_role(p, leader, fair_share)
            edge_str = f"+{edge:.1f}" if edge >= 0 else f"{edge:.1f}"
            out.append(f"\n👤 {p['name']} — {p['equity']:.1f}% (edge {edge_str} п.п.)")
            out.append(f"   {role}")
            out.append(f"   → {action}")
            trend = self._format_trend(p["name"])
            if trend:
                out.append(f"   📈 {trend}")

        out.append("\n" + "-" * 50)
        out.append("👹 ВРАГИ:")
        for opp in active_opps:
            style = opp.get("style", "unknown")
            range_desc = opp.get("custom_range_str") or STYLE_DESC[style]
            out.append(f" • {opp['name']}: угроза {opp['equity']:.1f}% | {range_desc}")
        out.append("=" * 50)

        self.write_analysis("\n".join(out))
        self.draw_equity_chart(active_team, active_opps)

        self.session_history.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode_label,
            "results": {p["name"]: p["equity"] for p in active_team + active_opps},
        })
        self.save_history()


def card_to_str(card_int):
    suits = {1: '♠', 2: '♥', 4: '♦', 8: '♣'}
    return f"{Card.STR_RANKS[Card.get_rank_int(card_int)]}{suits.get(Card.get_suit_int(card_int), '?')}"


def card_to_input_str(card_int):
    suits = {1: 's', 2: 'h', 4: 'd', 8: 'c'}
    return f"{Card.STR_RANKS[Card.get_rank_int(card_int)]}{suits.get(Card.get_suit_int(card_int), '?')}"


if __name__ == "__main__":
    root = tk.Tk()
    app = PokerApp(root)
    root.mainloop()