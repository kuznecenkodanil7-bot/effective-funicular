"""
ПРОТОКОЛ: СОБЕСЕДНИК
Desktop-игра на Python + Pygame.

Запуск локально:
    pip install -r requirements.txt
    python main.py

Управление:
    1/2/3, Enter — выбор в консольном прологе и звонках
    WASD — движение
    Shift — бег
    Мышь — направление взгляда/фонарика
    E — взаимодействие с таблетками, телефонами, терминалом
    R — рестарт после смерти/победы
    Esc — выход
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    import pygame
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Pygame не установлен. Выполни: pip install -r requirements.txt"
    ) from exc


WIDTH, HEIGHT = 1280, 720
FPS = 60
SAVE_PATH = Path.home() / ".protocol_sobesednik_save.json"

# Включи True, если хочешь, чтобы игра реально закрывалась при провале.
# По умолчанию сделана имитация закрытия, чтобы тестировать было удобнее.
REAL_CLOSE_ON_DEATH = False

COLORS = {
    "black": (4, 5, 6),
    "console_bg": (0, 13, 7),
    "console_green": (82, 255, 126),
    "green_dim": (30, 135, 68),
    "white": (220, 228, 224),
    "gray": (82, 88, 89),
    "red": (210, 42, 45),
    "red_dark": (75, 10, 15),
    "yellow": (245, 210, 74),
    "blue": (85, 160, 255),
    "cyan": (90, 255, 220),
    "floor": (20, 24, 25),
    "wall": (60, 66, 68),
    "wall_dark": (38, 42, 44),
    "pill": (236, 240, 230),
    "phone": (73, 126, 185),
    "terminal": (60, 220, 120),
}


@dataclass
class Choice:
    text: str
    tone: Optional[str] = None
    action: Optional[Callable[["Game"], None]] = None


@dataclass
class DialogueNode:
    operator_lines: list[str]
    choices: list[Choice]


@dataclass
class Entity:
    x: float
    y: float
    w: float
    h: float
    kind: str
    active: bool = True
    label: str = ""

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y), int(self.w), int(self.h))

    @property
    def center(self) -> pygame.Vector2:
        return pygame.Vector2(self.x + self.w / 2, self.y + self.h / 2)


@dataclass
class Question:
    text: str
    options: list[str]
    correct_index: Optional[int]  # None значит любой ответ засчитывается
    operator_success: str
    operator_fail: str


class Text:
    def __init__(self) -> None:
        pygame.font.init()
        # SysFont подставит доступный системный шрифт. На Windows обычно Consolas.
        self.console = pygame.font.SysFont("consolas", 22)
        self.console_big = pygame.font.SysFont("consolas", 38, bold=True)
        self.ui = pygame.font.SysFont("arial", 22)
        self.ui_big = pygame.font.SysFont("arial", 36, bold=True)
        self.small = pygame.font.SysFont("arial", 18)

    def draw(self, surf: pygame.Surface, text: str, pos: tuple[int, int], font: pygame.font.Font,
             color: tuple[int, int, int], center: bool = False) -> pygame.Rect:
        img = font.render(text, True, color)
        rect = img.get_rect()
        if center:
            rect.center = pos
        else:
            rect.topleft = pos
        surf.blit(img, rect)
        return rect

    def wrap(self, text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            test = word if not current else f"{current} {word}"
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def draw_wrapped(self, surf: pygame.Surface, text: str, x: int, y: int, font: pygame.font.Font,
                     color: tuple[int, int, int], max_width: int, line_gap: int = 6) -> int:
        for line in self.wrap(text, font, max_width):
            self.draw(surf, line, (x, y), font, color)
            y += font.get_height() + line_gap
        return y


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def distance(a: pygame.Vector2, b: pygame.Vector2) -> float:
    return (a - b).length()


def angle_between(a: pygame.Vector2, b: pygame.Vector2) -> float:
    if a.length_squared() == 0 or b.length_squared() == 0:
        return 180.0
    a = a.normalize()
    b = b.normalize()
    dot = clamp(a.dot(b), -1.0, 1.0)
    return math.degrees(math.acos(dot))


class Game:
    def __init__(self) -> None:
        pygame.init()
        # Отключаем автоповтор клавиш, чтобы Enter/Space не выбирали ответы много раз подряд.
        pygame.key.set_repeat(0)
        pygame.display.set_caption("ПРОТОКОЛ: СОБЕСЕДНИК")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.text = Text()
        self.rng = random.Random()
        self.username = os.environ.get("USERNAME") or os.environ.get("USER") or "ПОДОПЫТНЫЙ"

        self.running = True
        self.state = "prologue"
        self.last_dt = 0.0
        self.flash_timer = 0.0
        self.noise_timer = 0.0
        self.message_log: list[str] = []
        self.ephemeral_message = ""
        self.ephemeral_timer = 0.0

        self.save_data = self.load_save()
        self.prologue_nodes = self.build_prologue()
        self.node_index = 0
        self.choice_index = 0
        self.display_lines: list[str] = []
        self.type_queue: list[str] = []
        self.current_typing = ""
        self.type_timer = 0.0
        self.type_speed = 0.018
        self.prologue_started = False
        self.refusal_count = 0
        self.tone = "нейтральный"
        self.transition_timer = 0.0
        self.prologue_input_lock = 0.0

        self.world_w = 2400
        self.world_h = 1600
        self.player = pygame.Vector2(260, 260)
        self.player_radius = 16
        self.player_speed = 190
        self.camera = pygame.Vector2(0, 0)
        self.mouse_world = pygame.Vector2(0, 0)
        self.obstacles: list[pygame.Rect] = []
        self.pills: list[Entity] = []
        self.phones: list[Entity] = []
        self.terminal = Entity(2100, 1300, 72, 54, "terminal", True, "RESET")
        self.pill_timer = 180.0
        self.pill_timer_max = 180.0
        self.pills_used = 0
        self.calls_answered = 0
        self.phone_interval = 70.0
        self.phone_countdown = 25.0
        self.ringing_phone: Optional[Entity] = None
        self.ring_answer_timer = 0.0
        self.phone_question: Optional[Question] = None
        self.phone_choice_index = 0
        self.silhouette_level = int(self.save_data.get("infection", 0))
        self.silhouette = pygame.Vector2(900, 900)
        self.silhouette_cooldown = 0.0
        self.game_over_reason = ""

    # ---------- Save / restart ----------

    def load_save(self) -> dict:
        if SAVE_PATH.exists():
            try:
                return json.loads(SAVE_PATH.read_text(encoding="utf-8"))
            except Exception:
                return {"deaths": 0, "infection": 0, "last_tone": "нейтральный"}
        return {"deaths": 0, "infection": 0, "last_tone": "нейтральный"}

    def write_save(self) -> None:
        try:
            SAVE_PATH.write_text(json.dumps(self.save_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def reset_all(self) -> None:
        self.state = "prologue"
        self.node_index = 0
        self.choice_index = 0
        self.display_lines.clear()
        self.type_queue.clear()
        self.current_typing = ""
        self.prologue_started = False
        self.refusal_count = 0
        self.tone = "нейтральный"
        self.transition_timer = 0.0
        self.prologue_input_lock = 0.0
        self.flash_timer = 0.0
        self.ephemeral_message = ""
        self.ephemeral_timer = 0.0

    def start_main_game(self) -> None:
        self.state = "game"
        self.player.update(260, 260)
        self.camera.update(0, 0)
        self.pill_timer_max = 180.0 if self.refusal_count < 3 else 150.0
        if self.tone == "агрессивный":
            self.pill_timer_max *= 0.90
        self.pill_timer = self.pill_timer_max
        self.pills_used = 0
        self.calls_answered = 0
        self.phone_interval = 70.0
        self.phone_countdown = 25.0
        self.ringing_phone = None
        self.ring_answer_timer = 0.0
        self.phone_question = None
        self.phone_choice_index = 0
        self.silhouette_level = int(self.save_data.get("infection", 0))
        if self.refusal_count >= 3:
            self.silhouette_level = max(self.silhouette_level, 1)
        self.silhouette = pygame.Vector2(1300, 980)
        self.build_world()
        self.ephemeral_message = "НАЙДИ ТАБЛЕТКУ. ОТВЕЧАЙ НА ЗВОНКИ. НЕ СМОТРИ В СТОРОНУ."
        self.ephemeral_timer = 5.0

    def build_world(self) -> None:
        self.obstacles = []
        # Границы мира.
        self.obstacles.extend([
            pygame.Rect(0, 0, self.world_w, 40),
            pygame.Rect(0, self.world_h - 40, self.world_w, 40),
            pygame.Rect(0, 0, 40, self.world_h),
            pygame.Rect(self.world_w - 40, 0, 40, self.world_h),
        ])
        # Коридоры/комнаты медицинского комплекса.
        wall_specs = [
            (420, 40, 40, 520), (40, 560, 780, 40), (820, 250, 40, 560),
            (1160, 40, 40, 440), (1160, 610, 40, 680), (1500, 360, 40, 640),
            (1840, 40, 40, 540), (1840, 730, 40, 830), (420, 920, 780, 40),
            (40, 1240, 1080, 40), (1500, 1240, 860, 40), (2040, 360, 40, 420),
            (570, 720, 160, 42), (1010, 780, 170, 42), (1370, 970, 160, 42),
        ]
        self.obstacles.extend([pygame.Rect(*spec) for spec in wall_specs])

        self.pills = [
            Entity(345, 485, 26, 18, "pill", True, "таблетка"),
            Entity(640, 1110, 26, 18, "pill", True, "таблетка"),
            Entity(1035, 660, 26, 18, "pill", True, "таблетка"),
            Entity(1365, 250, 26, 18, "pill", True, "таблетка"),
            Entity(1740, 1120, 26, 18, "pill", True, "таблетка"),
            Entity(2180, 620, 26, 18, "pill", True, "таблетка"),
        ]
        self.phones = [
            Entity(540, 260, 42, 58, "phone", True, "телефон 01"),
            Entity(980, 1060, 42, 58, "phone", True, "телефон 02"),
            Entity(1325, 540, 42, 58, "phone", True, "телефон 03"),
            Entity(1985, 960, 42, 58, "phone", True, "телефон 04"),
            Entity(2190, 1360, 42, 58, "phone", True, "телефон 05"),
        ]

    # ---------- Prologue ----------

    def build_prologue(self) -> list[DialogueNode]:
        def set_tone(tone: str) -> Callable[["Game"], None]:
            def inner(game: "Game") -> None:
                game.tone = tone
                game.save_data["last_tone"] = tone
                game.write_save()
            return inner

        def accept(game: "Game") -> None:
            game.state = "transition"
            game.transition_timer = 0.0
            game.type_queue.clear()
            game.current_typing = ""

        def refuse(game: "Game") -> None:
            game.refusal_count += 1
            if game.refusal_count >= 3:
                game.queue_lines([
                    "Оператор: Ты думаешь, у тебя есть выбор?",
                    "Оператор: Всегда был только один путь.",
                    ">>> КОНСОЛЬ ПРИНУДИТЕЛЬНО ЗАКРЫВАЕТСЯ",
                ])
                game.flash_timer = 1.0
                game.state = "transition"
                game.transition_timer = 0.0
            else:
                game.queue_lines([
                    "Оператор: Отказ — тоже выбор.",
                    "Оператор: И у каждого выбора есть последствия.",
                    "Оператор: Давай попробуем ещё раз. Скажи: Я ГОТОВ.",
                ])

        return [
            DialogueNode(
                [
                    ">>> УСТАНОВЛЕНО СОЕДИНЕНИЕ С: ПОДОПЫТНЫЙ_#" + self.username.upper(),
                    ">>> СТАТУС: ПЕРВИЧНЫЙ КОНТАКТ",
                    "Оператор: Привет.",
                    "Оператор: Я вижу, что ты запустил эту программу.",
                    "Оператор: Ты один?",
                ],
                [
                    Choice("Кто ты? Как ты меня нашёл?", "агрессивный", set_tone("агрессивный")),
                    Choice("Откуда ты знаешь, что я один? Ты меня видишь?", "подозрительный", set_tone("подозрительный")),
                    Choice("Да... я один. Что тебе нужно?", "пассивный", set_tone("пассивный")),
                ],
            ),
            DialogueNode(
                [
                    "Оператор: Не важно, кто я. Важно то, что ты уже здесь.",
                    "Оператор: Давай уточним кое-что.",
                    "Оператор: Ты помнишь, как сюда попал?",
                ],
                [
                    Choice("Я запустил игру. Это всё."),
                    Choice("Я не помню. Где я?"),
                    Choice("Пожалуйста, просто скажи, что происходит."),
                ],
            ),
            DialogueNode(
                [
                    "Оператор: Ты выбрал. Ты запустил. Ты здесь.",
                    "Оператор: Слушай внимательно.",
                    "Оператор: Чувство страха — не лекарство.",
                    "Оператор: А лекарство — вот оно.",
                    "             ████████████",
                    "             ██   ██   ██",
                    "             ██   ██   ██",
                    "             ████████████",
                    "Оператор: Ты знаешь, что это?",
                ],
                [
                    Choice("Таблетка. Ты хочешь, чтобы я её принял?"),
                    Choice("Это ловушка. Ничего не принимаю."),
                    Choice("Я... не знаю. Страшно."),
                ],
            ),
            DialogueNode(
                [
                    "Оператор: Посмотри на свои руки.",
                    "Оператор: ...",
                    "Оператор: Ты чувствуешь, что теряешь контроль?",
                ],
                [
                    Choice("Да. И я ненавижу это."),
                    Choice("Ты манипулируешь мной. Я это вижу."),
                    Choice("Да... я не понимаю, что происходит."),
                ],
            ),
            DialogueNode(
                [
                    "Оператор: Мы говорим уже слишком долго.",
                    "Оператор: Ты заметил? Время течёт иначе здесь.",
                    "Оператор: Я предлагаю тебе выбор.",
                    "Оператор: Последний в этой... игре.",
                    "",
                    "╔══════════════════════════════════════╗",
                    "║  Ты готов принять таблетку?          ║",
                    "║  Скажи: Я ГОТОВ.                     ║",
                    "╚══════════════════════════════════════╝",
                ],
                [
                    Choice("Я ГОТОВ", action=accept),
                    Choice("Нет. Я не готов.", action=refuse),
                    Choice("Что будет, если я откажусь?", action=refuse),
                ],
            ),
        ]

    def queue_lines(self, lines: list[str]) -> None:
        self.type_queue.extend(lines)

    def begin_node(self) -> None:
        node = self.prologue_nodes[self.node_index]
        self.queue_lines(node.operator_lines)
        self.prologue_started = True

    def update_typing(self, dt: float) -> None:
        if not self.prologue_started:
            self.begin_node()
        if self.current_typing == "" and self.type_queue:
            self.current_typing = self.type_queue.pop(0)
            self.display_lines.append("")
        if self.current_typing:
            self.type_timer += dt
            chars = max(1, int(self.type_timer / self.type_speed))
            self.type_timer = 0.0
            add = self.current_typing[:chars]
            self.current_typing = self.current_typing[chars:]
            self.display_lines[-1] += add
            if len(self.display_lines) > 22:
                self.display_lines = self.display_lines[-22:]

    def handle_prologue_key(self, key: int) -> None:
        # Защита от ситуации, когда игрок зажал Enter/Space:
        # раньше из-за этого один ответ мог добавляться в историю много раз подряд.
        if self.prologue_input_lock > 0:
            return

        if self.type_queue or self.current_typing:
            # Enter/Space ускоряет печать текущего блока, но НЕ выбирает следующий ответ
            # в тот же момент. После пропуска ставим короткую блокировку ввода.
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                if self.current_typing:
                    self.display_lines[-1] += self.current_typing
                    self.current_typing = ""
                while self.type_queue:
                    self.display_lines.append(self.type_queue.pop(0))
                if len(self.display_lines) > 18:
                    self.display_lines = self.display_lines[-18:]
                self.prologue_input_lock = 0.22
            return

        node = self.prologue_nodes[self.node_index]
        if key in (pygame.K_UP, pygame.K_w):
            self.choice_index = (self.choice_index - 1) % len(node.choices)
            self.prologue_input_lock = 0.08
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.choice_index = (self.choice_index + 1) % len(node.choices)
            self.prologue_input_lock = 0.08
        elif key in (pygame.K_1, pygame.K_KP1):
            self.choice_index = 0
            self.choose_prologue()
        elif key in (pygame.K_2, pygame.K_KP2) and len(node.choices) > 1:
            self.choice_index = 1
            self.choose_prologue()
        elif key in (pygame.K_3, pygame.K_KP3) and len(node.choices) > 2:
            self.choice_index = 2
            self.choose_prologue()
        elif key == pygame.K_RETURN:
            self.choose_prologue()

    def choose_prologue(self) -> None:
        node = self.prologue_nodes[self.node_index]
        choice = node.choices[self.choice_index]
        self.display_lines.append(f"> {choice.text}")
        if len(self.display_lines) > 18:
            self.display_lines = self.display_lines[-18:]
        self.prologue_input_lock = 0.25
        if choice.action:
            choice.action(self)
            return
        # Разные реакции, но все ведут к следующему ключевому узлу.
        if self.node_index == 0:
            if choice.tone == "агрессивный":
                self.queue_lines(["Оператор: Угроза в первом вопросе. Инстинкты работают.", ">>> ФЛАГ: ТОН_АГРЕССИВНЫЙ"])
            elif choice.tone == "подозрительный":
                self.queue_lines(["Оператор: Ты задаёшь правильные вопросы.", ">>> ФЛАГ: ТОН_ПОДОЗРИТЕЛЬНЫЙ"])
            else:
                self.queue_lines(["Оператор: Честность. Или страх под видом честности?", ">>> ФЛАГ: ТОН_ПАССИВНЫЙ"])
        elif self.node_index == 1:
            self.queue_lines(["Оператор: Выход — не туда, куда ты думаешь."])
        elif self.node_index == 2:
            self.queue_lines(["Оператор: Это не ловушка. Это протокол."])
        elif self.node_index == 3:
            self.queue_lines(["Оператор: Непонимание — первый шаг к принятию."])
        self.node_index = min(self.node_index + 1, len(self.prologue_nodes) - 1)
        self.choice_index = 0
        self.prologue_started = False

    # ---------- Phone questions ----------

    def build_question(self) -> Question:
        stage = self.calls_answered + 1
        if stage == 1:
            number = random.choice([3, 7, 14])
            return Question(
                "Какое число я загадал?",
                ["3", "7", "14"],
                [3, 7, 14].index(number),
                "Оператор: Хорошо. Связь работает.",
                "Оператор: Неправильно. Он уже ближе.",
            )
        if stage == 2:
            amount = sum(1 for p in self.pills if p.active)
            opts = [str(max(0, amount - 1)), str(amount), str(amount + 1)]
            return Question(
                "Сколько таблеток осталось в комплексе?",
                opts,
                1,
                "Оператор: Ты считаешь. Значит, ещё жив.",
                "Оператор: Ты даже не знаешь, сколько у тебя времени.",
            )
        if stage == 3:
            return Question(
                "Как меня зовут?",
                ["Оператор", "Собеседник", "Ты не говорил"],
                2,
                "Оператор: Верно. Имя — это слабость.",
                "Оператор: Я никогда не называл себя. Ты придумал это сам.",
            )
        if stage == 4:
            return Question(
                "Какой пин был на первой записке?",
                ["14", "042", "314"],
                0,
                "Оператор: Память возвращается кусками.",
                "Оператор: Шкафы любят менять коды.",
            )
        return Question(
            "Почему ты продолжаешь принимать таблетки?",
            ["Чтобы выжить", "Потому что ты заставляешь", "Я не знаю"],
            None,
            "Оператор: Правильно. Потому что не знаешь.",
            "Оператор: Ответ не имеет значения.",
        )

    # ---------- Main loop ----------

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self.last_dt = dt
            self.handle_events()
            self.update(dt)
            self.draw()
        pygame.quit()

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif self.state == "prologue":
                    self.handle_prologue_key(event.key)
                elif self.state == "phone":
                    self.handle_phone_key(event.key)
                elif self.state in ("game_over", "win") and event.key == pygame.K_r:
                    self.reset_all()

    def update(self, dt: float) -> None:
        self.flash_timer = max(0.0, self.flash_timer - dt)
        self.prologue_input_lock = max(0.0, self.prologue_input_lock - dt)
        self.noise_timer += dt
        if self.ephemeral_timer > 0:
            self.ephemeral_timer -= dt
        else:
            self.ephemeral_message = ""

        if self.state == "prologue":
            self.update_typing(dt)
        elif self.state == "transition":
            self.transition_timer += dt
            if self.transition_timer >= 6.2:
                self.start_main_game()
        elif self.state == "game":
            self.update_game(dt)
        elif self.state == "phone":
            self.update_phone(dt)

    def update_game(self, dt: float) -> None:
        self.update_mouse_world()
        self.update_player(dt)
        self.update_timers(dt)
        self.update_silhouette(dt)
        self.update_camera()

    def update_mouse_world(self) -> None:
        mx, my = pygame.mouse.get_pos()
        self.mouse_world = pygame.Vector2(mx, my) + self.camera

    def update_player(self, dt: float) -> None:
        keys = pygame.key.get_pressed()
        move = pygame.Vector2(0, 0)
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            move.y -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            move.y += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            move.x -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            move.x += 1
        if move.length_squared() > 0:
            move = move.normalize()
        speed = self.player_speed * (1.35 if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] else 1.0)
        delta = move * speed * dt
        self.try_move(delta)

        if keys[pygame.K_e]:
            self.try_interact()

    def try_move(self, delta: pygame.Vector2) -> None:
        if delta.x:
            self.player.x += delta.x
            if self.collides_player():
                self.player.x -= delta.x
        if delta.y:
            self.player.y += delta.y
            if self.collides_player():
                self.player.y -= delta.y
        self.player.x = clamp(self.player.x, 60, self.world_w - 60)
        self.player.y = clamp(self.player.y, 60, self.world_h - 60)

    def collides_player(self) -> bool:
        pr = pygame.Rect(int(self.player.x - self.player_radius), int(self.player.y - self.player_radius),
                         self.player_radius * 2, self.player_radius * 2)
        return any(pr.colliderect(wall) for wall in self.obstacles)

    def try_interact(self) -> None:
        # Таблетки.
        for pill in self.pills:
            if pill.active and distance(self.player, pill.center) < 48:
                pill.active = False
                self.pills_used += 1
                self.pill_timer_max = max(65.0, self.pill_timer_max - 14.0)
                self.pill_timer = self.pill_timer_max
                self.ephemeral_message = "ТАБЛЕТКА ПРИНЯТА. ТАЙМЕР СБРОШЕН."
                self.ephemeral_timer = 2.4
                return

        # Звонящий телефон.
        if self.ringing_phone and distance(self.player, self.ringing_phone.center) < 72:
            self.state = "phone"
            self.phone_question = self.build_question()
            self.phone_choice_index = 0
            self.flash_timer = 0.25
            return

        # Терминал победы.
        if distance(self.player, self.terminal.center) < 80:
            if self.pills_used >= 4 and self.calls_answered >= 3:
                self.state = "win"
                self.save_data["infection"] = max(0, int(self.save_data.get("infection", 0)) - 1)
                self.write_save()
            else:
                self.ephemeral_message = "ТЕРМИНАЛ МОЛЧИТ: НУЖНО 4 ТАБЛЕТКИ И 3 ОТВЕТА НА ЗВОНКИ."
                self.ephemeral_timer = 3.0

    def update_timers(self, dt: float) -> None:
        self.pill_timer -= dt
        if self.pill_timer <= 0:
            self.trigger_game_over("ТЫ НЕ НАШЁЛ ТАБЛЕТКУ. ПРОТОКОЛ ЗАКРЫТ.")
            return

        if self.ringing_phone:
            self.ring_answer_timer -= dt
            if self.ring_answer_timer <= 0:
                self.fail_phone("ТЫ НЕ ОТВЕТИЛ НА ЗВОНОК.")
        else:
            self.phone_countdown -= dt
            if self.phone_countdown <= 0:
                active_phones = [p for p in self.phones if p.active]
                self.ringing_phone = min(active_phones, key=lambda p: distance(self.player, p.center)) if active_phones else None
                self.ring_answer_timer = 25.0
                self.ephemeral_message = "ЗВОНОК. НАЙДИ ТЕЛЕФОН."
                self.ephemeral_timer = 4.0

    def update_phone(self, dt: float) -> None:
        self.ring_answer_timer -= dt
        if self.ring_answer_timer <= 0:
            self.fail_phone("ТЫ МОЛЧАЛ СЛИШКОМ ДОЛГО.")

    def handle_phone_key(self, key: int) -> None:
        if not self.phone_question:
            return
        if key in (pygame.K_UP, pygame.K_w):
            self.phone_choice_index = (self.phone_choice_index - 1) % len(self.phone_question.options)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.phone_choice_index = (self.phone_choice_index + 1) % len(self.phone_question.options)
        elif key in (pygame.K_1, pygame.K_KP1):
            self.phone_choice_index = 0
            self.answer_phone()
        elif key in (pygame.K_2, pygame.K_KP2):
            self.phone_choice_index = 1
            self.answer_phone()
        elif key in (pygame.K_3, pygame.K_KP3):
            self.phone_choice_index = 2
            self.answer_phone()
        elif key == pygame.K_RETURN:
            self.answer_phone()

    def answer_phone(self) -> None:
        q = self.phone_question
        if not q:
            return
        correct = q.correct_index is None or self.phone_choice_index == q.correct_index
        if correct:
            self.calls_answered += 1
            self.ephemeral_message = q.operator_success
            self.ephemeral_timer = 3.0
            if self.silhouette_level > 0 and self.calls_answered % 2 == 0:
                self.silhouette_level -= 1
        else:
            self.ephemeral_message = q.operator_fail
            self.ephemeral_timer = 3.0
            self.raise_silhouette()
        self.ringing_phone = None
        self.phone_question = None
        self.state = "game"
        self.phone_interval = max(35.0, self.phone_interval - 7.0)
        self.phone_countdown = self.phone_interval

    def fail_phone(self, reason: str) -> None:
        self.ephemeral_message = reason
        self.ephemeral_timer = 3.0
        self.ringing_phone = None
        self.phone_question = None
        self.state = "game"
        self.raise_silhouette()
        self.phone_interval = max(35.0, self.phone_interval - 7.0)
        self.phone_countdown = self.phone_interval

    def raise_silhouette(self) -> None:
        self.silhouette_level += 1
        self.flash_timer = 0.8
        if self.silhouette_level == 1:
            # Появляется далеко, но в зоне мира.
            direction = pygame.Vector2(random.choice([-1, 1]), random.choice([-1, 1])).normalize()
            self.silhouette = self.player + direction * 520
            self.silhouette.x = clamp(self.silhouette.x, 80, self.world_w - 80)
            self.silhouette.y = clamp(self.silhouette.y, 80, self.world_h - 80)
        if self.silhouette_level >= 5:
            self.trigger_game_over("СИЛУЭТ КОСНУЛСЯ ТЕБЯ.")

    def update_silhouette(self, dt: float) -> None:
        if self.silhouette_level <= 0:
            return
        aim = self.mouse_world - self.player
        to_silhouette = self.silhouette - self.player
        looking = angle_between(aim, to_silhouette) < 32 and to_silhouette.length() < 650
        self.silhouette_cooldown = max(0.0, self.silhouette_cooldown - dt)

        if not looking:
            speed = 42 + self.silhouette_level * 27
            if to_silhouette.length_squared() > 0:
                self.silhouette -= to_silhouette.normalize() * speed * dt
        elif self.silhouette_level >= 3 and self.silhouette_cooldown <= 0:
            # На высоком уровне при долгом взгляде он глючит за спину игрока.
            if random.random() < 0.006:
                back = (self.player - self.mouse_world)
                if back.length_squared() > 0:
                    self.silhouette = self.player + back.normalize() * 240
                    self.silhouette_cooldown = 3.0

        if distance(self.player, self.silhouette) < 30 + self.silhouette_level * 3:
            self.trigger_game_over("СИЛУЭТ ДОШЁЛ ДО ТЕБЯ.")

    def trigger_game_over(self, reason: str) -> None:
        self.game_over_reason = reason
        self.save_data["deaths"] = int(self.save_data.get("deaths", 0)) + 1
        self.save_data["infection"] = min(4, int(self.save_data.get("infection", 0)) + 1)
        self.write_save()
        if REAL_CLOSE_ON_DEATH:
            pygame.quit()
            sys.exit(0)
        self.state = "game_over"

    def update_camera(self) -> None:
        self.camera.x = clamp(self.player.x - WIDTH / 2, 0, self.world_w - WIDTH)
        self.camera.y = clamp(self.player.y - HEIGHT / 2, 0, self.world_h - HEIGHT)

    # ---------- Drawing ----------

    def draw(self) -> None:
        if self.state == "prologue":
            self.draw_prologue()
        elif self.state == "transition":
            self.draw_transition()
        elif self.state in ("game", "phone"):
            self.draw_game()
            if self.state == "phone":
                self.draw_phone_overlay()
        elif self.state == "game_over":
            self.draw_game_over()
        elif self.state == "win":
            self.draw_win()
        pygame.display.flip()

    def draw_prologue(self) -> None:
        self.screen.fill(COLORS["console_bg"])
        # scanlines
        for y in range(0, HEIGHT, 4):
            pygame.draw.line(self.screen, (0, 30, 15), (0, y), (WIDTH, y))
        pygame.draw.rect(self.screen, COLORS["green_dim"], (38, 34, WIDTH - 76, HEIGHT - 68), 2)
        self.text.draw(self.screen, "ПРОТОКОЛ: СОБЕСЕДНИК", (54, 48), self.text.console_big, COLORS["console_green"])

        # История диалога теперь рисуется в отдельной области.
        # Нижняя часть экрана зарезервирована только под варианты ответа.
        message_rect = pygame.Rect(54, 104, WIDTH - 108, HEIGHT - 325)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(message_rect)
        y = message_rect.y
        for line in self.display_lines[-13:]:
            y = self.text.draw_wrapped(
                self.screen,
                line,
                message_rect.x,
                y,
                self.text.console,
                COLORS["console_green"],
                message_rect.width,
                2,
            )
            if y > message_rect.bottom - 24:
                break
        if self.current_typing and y < message_rect.bottom - 24:
            self.text.draw(self.screen, "_", (message_rect.x + random.randint(0, 4), y), self.text.console, COLORS["console_green"])
        self.screen.set_clip(old_clip)

        if not self.type_queue and not self.current_typing:
            node = self.prologue_nodes[self.node_index]
            panel = pygame.Rect(54, HEIGHT - 205, WIDTH - 108, 148)
            pygame.draw.rect(self.screen, COLORS["console_bg"], panel)
            pygame.draw.rect(self.screen, COLORS["green_dim"], panel, 1)
            choice_y = panel.y + 16
            for i, choice in enumerate(node.choices):
                color = COLORS["yellow"] if i == self.choice_index else COLORS["console_green"]
                prefix = ">" if i == self.choice_index else " "
                self.text.draw(self.screen, f"{prefix} {i + 1}. {choice.text}", (panel.x + 18, choice_y), self.text.console, color)
                choice_y += 34
            self.text.draw(self.screen, "1/2/3 или Enter — выбрать. Space — пропустить печать.",
                           (70, HEIGHT - 42), self.text.small, COLORS["green_dim"])
        else:
            self.text.draw(self.screen, "Space/Enter — допечатать сообщение.",
                           (70, HEIGHT - 42), self.text.small, COLORS["green_dim"])

        self.draw_noise_overlay(alpha=35)

    def draw_transition(self) -> None:
        self.screen.fill(COLORS["black"])
        t = self.transition_timer
        cx, cy = WIDTH // 2, HEIGHT // 2
        if t < 1.2:
            self.text.draw(self.screen, "Оператор: Хорошо.", (cx, cy - 60), self.text.console_big, COLORS["console_green"], True)
            self.text.draw(self.screen, "Оператор: Очень хорошо.", (cx, cy), self.text.console_big, COLORS["console_green"], True)
        elif t < 3.4:
            lines = [
                ">>> ПОДТВЕРЖДЕНИЕ ПРИНЯТО",
                ">>> ИНИЦИАЛИЗАЦИЯ ПРОТОКОЛА: СЕАНС_АЛЬФА",
                ">>> ЗАГРУЗКА МОДУЛЯ: ПЕРЦЕПЦИЯ",
                ">>> ЗАГРУЗКА МОДУЛЯ: КОГНИЦИЯ",
                ">>> ЗАГРУЗКА МОДУЛЯ: ДВИЖЕНИЕ",
            ]
            y = 170
            for i, line in enumerate(lines):
                if t > 1.2 + i * 0.35:
                    x = 120 + random.randint(-3, 3)
                    self.text.draw(self.screen, line, (x, y), self.text.console_big, COLORS["console_green"])
                    y += 64
        elif t < 4.6:
            self.screen.fill((230, 238, 235) if int(t * 12) % 2 == 0 else COLORS["black"])
            self.text.draw(self.screen, "...лёгкость", (cx, cy), self.text.console_big,
                           COLORS["black"] if int(t * 12) % 2 == 0 else COLORS["console_green"], True)
        else:
            self.text.draw(self.screen, "[ТИШИНА]", (cx, cy - 20), self.text.console_big, COLORS["gray"], True)
            self.text.draw(self.screen, "кто-то дышит рядом", (cx, cy + 36), self.text.console, COLORS["red"], True)
        self.draw_noise_overlay(alpha=65)

    def world_to_screen(self, pos: pygame.Vector2 | tuple[float, float]) -> tuple[int, int]:
        if isinstance(pos, tuple):
            x, y = pos
            return int(x - self.camera.x), int(y - self.camera.y)
        return int(pos.x - self.camera.x), int(pos.y - self.camera.y)

    def draw_game(self) -> None:
        self.screen.fill(COLORS["black"])
        floor_rect = pygame.Rect(-int(self.camera.x), -int(self.camera.y), self.world_w, self.world_h)
        pygame.draw.rect(self.screen, COLORS["floor"], floor_rect)
        self.draw_grid()
        self.draw_world_entities()
        self.draw_flashlight_and_darkness()
        self.draw_ui()
        self.draw_noise_overlay(alpha=25 + self.silhouette_level * 7)
        if self.flash_timer > 0:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((*COLORS["red"], int(100 * self.flash_timer)))
            self.screen.blit(overlay, (0, 0))

    def draw_grid(self) -> None:
        step = 80
        start_x = int(self.camera.x // step * step)
        start_y = int(self.camera.y // step * step)
        for x in range(start_x, int(self.camera.x + WIDTH) + step, step):
            sx = int(x - self.camera.x)
            pygame.draw.line(self.screen, (28, 31, 32), (sx, 0), (sx, HEIGHT))
        for y in range(start_y, int(self.camera.y + HEIGHT) + step, step):
            sy = int(y - self.camera.y)
            pygame.draw.line(self.screen, (28, 31, 32), (0, sy), (WIDTH, sy))

    def draw_world_entities(self) -> None:
        # walls
        for wall in self.obstacles:
            r = wall.move(-self.camera.x, -self.camera.y)
            if r.colliderect(self.screen.get_rect()):
                pygame.draw.rect(self.screen, COLORS["wall_dark"], r)
                pygame.draw.rect(self.screen, COLORS["wall"], r, 2)

        # terminal
        tr = self.terminal.rect.move(-self.camera.x, -self.camera.y)
        pygame.draw.rect(self.screen, (20, 60, 35), tr)
        pygame.draw.rect(self.screen, COLORS["terminal"], tr, 2)
        self.text.draw(self.screen, "RESET", (tr.x - 4, tr.y - 24), self.text.small, COLORS["terminal"])

        # phones
        for phone in self.phones:
            r = phone.rect.move(-self.camera.x, -self.camera.y)
            color = COLORS["yellow"] if phone is self.ringing_phone and int(pygame.time.get_ticks() / 250) % 2 == 0 else COLORS["phone"]
            pygame.draw.rect(self.screen, (20, 38, 56), r)
            pygame.draw.rect(self.screen, color, r, 3)
            pygame.draw.circle(self.screen, color, r.center, 6)
            if phone is self.ringing_phone:
                self.text.draw(self.screen, "ЗВОНОК", (r.x - 18, r.y - 25), self.text.small, COLORS["yellow"])

        # pills
        for pill in self.pills:
            if not pill.active:
                continue
            center = self.world_to_screen(pill.center)
            pr = pygame.Rect(0, 0, int(pill.w), int(pill.h))
            pr.center = center
            pygame.draw.ellipse(self.screen, COLORS["pill"], pr)
            pygame.draw.line(self.screen, COLORS["gray"], (pr.centerx, pr.top + 3), (pr.centerx, pr.bottom - 3), 1)

        # silhouette
        if self.silhouette_level > 0:
            sx, sy = self.world_to_screen(self.silhouette)
            size = 28 + self.silhouette_level * 7
            shadow = pygame.Surface((size * 3, size * 4), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (0, 0, 0, 230), (size, 0, size, size * 1.25))
            pygame.draw.rect(shadow, (0, 0, 0, 230), (int(size * 0.75), int(size * 0.9), int(size * 1.5), int(size * 2.3)), border_radius=18)
            pygame.draw.line(shadow, (0, 0, 0, 230), (int(size * 1.1), int(size * 2.4)), (int(size * 0.55), int(size * 3.7)), 6)
            pygame.draw.line(shadow, (0, 0, 0, 230), (int(size * 1.9), int(size * 2.4)), (int(size * 2.45), int(size * 3.7)), 6)
            self.screen.blit(shadow, (sx - size * 1.5, sy - size * 2.5))

        # player
        px, py = self.world_to_screen(self.player)
        pygame.draw.circle(self.screen, (190, 210, 205), (px, py), self.player_radius)
        pygame.draw.circle(self.screen, COLORS["cyan"], (px, py), self.player_radius, 2)
        aim = self.mouse_world - self.player
        if aim.length_squared() > 0:
            aim = aim.normalize()
            pygame.draw.line(self.screen, COLORS["cyan"], (px, py), (int(px + aim.x * 32), int(py + aim.y * 32)), 2)

    def draw_flashlight_and_darkness(self) -> None:
        darkness = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        darkness.fill((0, 0, 0, 185 + self.silhouette_level * 8))
        px, py = self.world_to_screen(self.player)
        aim = self.mouse_world - self.player
        if aim.length_squared() == 0:
            aim = pygame.Vector2(1, 0)
        aim = aim.normalize()
        left = aim.rotate(-30)
        right = aim.rotate(30)
        cone_len = 430
        cone = [(px, py), (int(px + left.x * cone_len), int(py + left.y * cone_len)),
                (int(px + aim.x * (cone_len + 130)), int(py + aim.y * (cone_len + 130))),
                (int(px + right.x * cone_len), int(py + right.y * cone_len))]
        pygame.draw.polygon(darkness, (0, 0, 0, 25), cone)
        pygame.draw.circle(darkness, (0, 0, 0, 55), (px, py), 135)
        self.screen.blit(darkness, (0, 0))

    def draw_ui(self) -> None:
        panel = pygame.Surface((WIDTH, 88), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 150))
        self.screen.blit(panel, (0, 0))
        remaining_pills = sum(1 for p in self.pills if p.active)
        timer_text = f"ДО СЛЕДУЮЩЕЙ ДОЗЫ: {int(self.pill_timer // 60):02d}:{int(self.pill_timer % 60):02d}"
        color = COLORS["red"] if self.pill_timer < 35 else COLORS["white"]
        self.text.draw(self.screen, timer_text, (26, 18), self.text.ui_big, color)
        self.text.draw(self.screen, f"Таблетки взято: {self.pills_used} | осталось: {remaining_pills}", (28, 58), self.text.small, COLORS["white"])
        if self.ringing_phone:
            p = self.ringing_phone.center
            direction = p - self.player
            text = f"📞 ЗВОНОК: {int(self.ring_answer_timer)} сек"
            self.text.draw(self.screen, text, (600, 18), self.text.ui_big, COLORS["yellow"])
            if direction.length_squared() > 0:
                direction = direction.normalize()
                center = pygame.Vector2(WIDTH - 80, 44)
                end = center + direction * 35
                pygame.draw.line(self.screen, COLORS["yellow"], center, end, 5)
                pygame.draw.circle(self.screen, COLORS["yellow"], (int(end.x), int(end.y)), 8)
        else:
            self.text.draw(self.screen, f"До звонка: {int(self.phone_countdown)} сек", (600, 24), self.text.ui, COLORS["white"])
        self.text.draw(self.screen, f"Силуэт: уровень {self.silhouette_level}/5", (960, 24), self.text.ui, COLORS["red"] if self.silhouette_level else COLORS["gray"])
        self.text.draw(self.screen, "WASD — ходить | Shift — бег | E — взаимодействие | мышь — смотреть", (770, 60), self.text.small, COLORS["gray"])

        if self.ephemeral_message:
            box = pygame.Surface((WIDTH, 52), pygame.SRCALPHA)
            box.fill((0, 0, 0, 175))
            self.screen.blit(box, (0, HEIGHT - 76))
            self.text.draw(self.screen, self.ephemeral_message, (WIDTH // 2, HEIGHT - 51), self.text.ui, COLORS["yellow"], True)

    def draw_phone_overlay(self) -> None:
        q = self.phone_question
        if not q:
            return
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 145))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(WIDTH // 2 - 340, HEIGHT // 2 - 210, 680, 420)
        pygame.draw.rect(self.screen, (8, 12, 14), panel, border_radius=8)
        pygame.draw.rect(self.screen, COLORS["yellow"], panel, 3, border_radius=8)
        self.text.draw(self.screen, "📞 ВХОДЯЩИЙ ВЫЗОВ", (panel.x + 34, panel.y + 28), self.text.ui_big, COLORS["yellow"])
        self.text.draw_wrapped(self.screen, "Оператор: " + q.text, panel.x + 34, panel.y + 96, self.text.ui_big, COLORS["white"], panel.w - 68)
        self.text.draw(self.screen, f"Осталось: {int(self.ring_answer_timer)} сек", (panel.x + 34, panel.y + 160), self.text.ui, COLORS["red"] if self.ring_answer_timer < 7 else COLORS["white"])
        y = panel.y + 218
        for i, opt in enumerate(q.options):
            r = pygame.Rect(panel.x + 54, y, panel.w - 108, 48)
            pygame.draw.rect(self.screen, (25, 28, 30), r, border_radius=6)
            pygame.draw.rect(self.screen, COLORS["yellow"] if i == self.phone_choice_index else COLORS["gray"], r, 2, border_radius=6)
            self.text.draw(self.screen, f"{i + 1}. {opt}", (r.x + 18, r.y + 12), self.text.ui, COLORS["yellow"] if i == self.phone_choice_index else COLORS["white"])
            y += 62
        self.text.draw(self.screen, "1/2/3 или Enter — ответить", (panel.centerx, panel.bottom - 32), self.text.small, COLORS["gray"], True)

    def draw_game_over(self) -> None:
        self.screen.fill(COLORS["black"])
        self.draw_noise_overlay(alpha=90)
        self.text.draw(self.screen, "CONNECTION LOST", (WIDTH // 2, HEIGHT // 2 - 110), self.text.console_big, COLORS["red"], True)
        self.text.draw_wrapped(self.screen, self.game_over_reason, WIDTH // 2 - 360, HEIGHT // 2 - 40, self.text.ui_big, COLORS["white"], 720)
        deaths = int(self.save_data.get("deaths", 0))
        infection = int(self.save_data.get("infection", 0))
        self.text.draw(self.screen, f"Оператор помнит. Смертей: {deaths}. Заражение: {infection}/4.",
                       (WIDTH // 2, HEIGHT // 2 + 70), self.text.ui, COLORS["yellow"], True)
        self.text.draw(self.screen, "R — начать заново | Esc — выйти", (WIDTH // 2, HEIGHT // 2 + 132), self.text.ui, COLORS["gray"], True)

    def draw_win(self) -> None:
        self.screen.fill((5, 18, 11))
        self.draw_noise_overlay(alpha=35)
        self.text.draw(self.screen, "ПРОТОКОЛ ПЕРЕЗАГРУЖЕН", (WIDTH // 2, HEIGHT // 2 - 120), self.text.console_big, COLORS["terminal"], True)
        self.text.draw_wrapped(
            self.screen,
            "Ты добрался до терминала, собрал достаточно таблеток и выдержал звонки. Оператор замолчал. Но файл памяти остался.",
            WIDTH // 2 - 420,
            HEIGHT // 2 - 40,
            self.text.ui_big,
            COLORS["white"],
            840,
        )
        self.text.draw(self.screen, "R — пройти снова | Esc — выйти", (WIDTH // 2, HEIGHT // 2 + 130), self.text.ui, COLORS["gray"], True)

    def draw_noise_overlay(self, alpha: int = 40) -> None:
        if alpha <= 0:
            return
        surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        if self.noise_timer > 0.02:
            self.noise_timer = 0.0
        for _ in range(80):
            x = random.randint(0, WIDTH)
            y = random.randint(0, HEIGHT)
            w = random.randint(1, 140)
            col = random.choice([(255, 255, 255, alpha), (0, 255, 90, alpha), (255, 0, 40, alpha)])
            pygame.draw.rect(surf, col, (x, y, w, 1))
        # vignette
        pygame.draw.rect(surf, (0, 0, 0, alpha + 30), (0, 0, WIDTH, 18))
        pygame.draw.rect(surf, (0, 0, 0, alpha + 30), (0, HEIGHT - 18, WIDTH, 18))
        pygame.draw.rect(surf, (0, 0, 0, alpha + 30), (0, 0, 18, HEIGHT))
        pygame.draw.rect(surf, (0, 0, 0, alpha + 30), (WIDTH - 18, 0, 18, HEIGHT))
        self.screen.blit(surf, (0, 0))


if __name__ == "__main__":
    Game().run()
