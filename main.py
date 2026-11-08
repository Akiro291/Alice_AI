#!/usr/bin/env python3
"""
Alice AI — локальный оркестратор агента.
Связывает Ollama (мозг) с MCP-серверами (руки).
Лимит шагов: 10. Всё логируется в agent.log.
"""

import json
import subprocess
import logging
import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

# ============================================================
# Настройка логирования
# ============================================================
LOG_FILE = Path(__file__).parent / "agent.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================
# Конфигурация агента
# ============================================================
@dataclass
class AgentConfig:
    model_name: str = "qwen2.5:14b"  # Имя модели в Ollama
    max_steps: int = 10              # Жёсткий лимит шагов


# ============================================================
# Оркестратор
# ============================================================
class AgentOrchestrator:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.mcp_servers: Dict[str, subprocess.Popen] = {}

    def load_mcp_config(self) -> Dict[str, Any]:
        """Читает mcp.json"""
        config_path = Path(__file__).parent / "mcp.json"
        if not config_path.exists():
            logger.error("mcp.json не найден")
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга mcp.json: {e}")
            return {}

    def start_mcp_servers(self) -> None:
        """Запускает MCP-серверы из mcp.json (пока просто поднимаем процессы)"""
        config = self.load_mcp_config()
        for server in config.get("servers", []):
            if not server.get("enabled", True):
                continue
            name = server.get("name")
            cmd = server.get("command")
            if not name or not cmd:
                continue
            try:
                # Разбиваем команду на список аргументов
                args = cmd.split()
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self.mcp_servers[name] = proc
                logger.info(f"MCP-сервер '{name}' запущен (PID {proc.pid})")
            except Exception as e:
                logger.error(f"Не удалось запустить MCP '{name}': {e}")

    def stop_mcp_servers(self) -> None:
        """Корректно останавливает все MCP-процессы"""
        for name, proc in list(self.mcp_servers.items()):
            if proc.poll() is None:  # ещё работает
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                    logger.info(f"MCP-сервер '{name}' остановлен")
                except subprocess.TimeoutExpired:
                    proc.kill()
                    logger.warning(f"MCP-сервер '{name}' принудительно убит")
                except Exception as e:
                    logger.error(f"Ошибка при остановке '{name}': {e}")
        self.mcp_servers.clear()

    def call_ollama(self, prompt: str) -> Optional[str]:
        """Отправляет промпт в Ollama и возвращает ответ"""
        try:
            result = subprocess.run(
                ["ollama", "run", self.config.model_name, prompt],
                capture_output=True,
                text=True,
                timeout=180,  # 3 минуты на ответ
                encoding="utf-8",
            )
            if result.returncode == 0:
                return result.stdout.strip()
            logger.error(f"Ollama вернула ошибку: {result.stderr.strip()}")
            return None
        except subprocess.TimeoutExpired:
            logger.error("Таймаут ожидания ответа от Ollama")
            return None
        except FileNotFoundError:
            logger.error("Команда 'ollama' не найдена. Убедись, что Ollama установлена и в PATH")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при вызове Ollama: {e}")
            return None

    def parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        Простой парсер вызовов инструментов из текста модели.
        Ищет конструкции вида: tool_name(arg1='value', arg2=123)
        """
        tool_calls = []
        # Ищем имя_функции(аргументы)
        pattern = r"(\w+)\((.*?)\)"
        matches = re.findall(pattern, response, re.DOTALL)

        for name, args_str in matches:
            # Пропускаем обычные слова, которые не похожи на инструменты
            if name.lower() in ("if", "for", "while", "print", "return", "def", "class"):
                continue

            args: Dict[str, Any] = {}
            if args_str.strip():
                # Разбиваем по запятым, учитывая возможные кавычки
                for part in re.split(r",(?=(?:[^'\"]*['\"][^'\"]*['\"])*[^'\"]*$)", args_str):
                    part = part.strip()
                    if "=" in part:
                        key, value = part.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip("'\"")
                        args[key] = value

            tool_calls.append({"name": name, "args": args})

        return tool_calls

    def execute_tool_call(self, tool_call: Dict[str, Any]) -> str:
        """
        Выполняет вызов инструмента.
        Сейчас — заглушка. Позже здесь будет реальный MCP-клиент.
        """
        name = tool_call["name"]
        args = tool_call["args"]
        logger.info(f"Вызов инструмента: {name}({args})")

        # Имитация (первый этап)
        name_lower = name.lower()
        if "windows" in name_lower or name_lower.startswith(("open_", "close_", "click", "type", "run_")):
            return f"✅ Windows-инструмент '{name}' выполнен (заглушка)"
        if "browser" in name_lower or "playwright" in name_lower or name_lower.startswith(("navigate", "goto", "click", "fill", "extract")):
            return f"✅ Browser-инструмент '{name}' выполнен (заглушка)"

        return f"⚠ Неизвестный инструмент: {name}"

    def build_prompt(self, task: str, history: List[str]) -> str:
        """Формирует промпт для модели"""
        history_text = "\n".join(history[-6:]) if history else "Пока нет истории."

        return f"""Ты — локальный AI-агент "Алиса". Ты работаешь строго по командам пользователя.

Правила:
1. Выполняй ТОЛЬКО поставленную задачу. Не придумывай свои цели.
2. Если задача выполнена — напиши слово TERMINATE и краткий отчёт.
3. Если нужно действие — вызови инструмент в формате:
   tool_name(arg1='value', arg2='value')
4. Не пиши длинных рассуждений. Действуй.
5. Если не получается — после нескольких попыток пиши TERMINATE и объясни проблему.

Доступные инструменты (примеры):
- browser_navigate(url='https://example.com')
- browser_click(selector='button.submit')
- browser_type(selector='input#search', text='запрос')
- windows_open_app(name='notepad')
- windows_run_powershell(command='Get-Process')

Текущая задача: {task}

История последних шагов:
{history_text}

Твой следующий шаг:"""

    def run_cycle(self, task: str) -> str:
        """Основной цикл агента"""
        self.start_mcp_servers()
        logger.info(f"===== Старт задачи: {task} =====")

        history: List[str] = []

        try:
            for step in range(1, self.config.max_steps + 1):
                logger.info(f"--- Шаг {step}/{self.config.max_steps} ---")

                prompt = self.build_prompt(task, history)
                response = self.call_ollama(prompt)

                if not response:
                    return "Ошибка: Ollama не отвечает. Проверь, запущена ли модель."

                logger.info(f"Ответ модели: {response[:300]}{'...' if len(response) > 300 else ''}")
                history.append(f"Шаг {step}: {response[:200]}")

                # Проверка на завершение
                if "TERMINATE" in response.upper():
                    return f"✅ Задача завершена моделью:\n{response}"

                # Парсим и выполняем инструменты
                tool_calls = self.parse_tool_calls(response)
                if tool_calls:
                    for tc in tool_calls:
                        result = self.execute_tool_call(tc)
                        logger.info(result)
                        history.append(f"Результат {tc['name']}: {result}")
                else:
                    logger.info("Модель не вызвала ни одного инструмента")

            return "❌ Лимит шагов (10) исчерпан. Задача не завершена."

        finally:
            self.stop_mcp_servers()
            logger.info("===== Цикл завершён =====")


# ============================================================
# Точка входа
# ============================================================
def main() -> None:
    config = AgentConfig()
    orchestrator = AgentOrchestrator(config)

    print("=" * 60)
    print("  ALICE AI — Локальный агент (Ollama + MCP)")
    print("=" * 60)
    print(f"  Модель:      {config.model_name}")
    print(f"  Лимит шагов: {config.max_steps}")
    print(f"  Лог:         {LOG_FILE}")
    print("=" * 60)
    print()

    task = input("Введите задачу для Алисы: ").strip()
    if not task:
        print("Задача не введена. Выход.")
        return

    try:
        result = orchestrator.run_cycle(task)
        print("\n" + "=" * 60)
        print("РЕЗУЛЬТАТ:")
        print(result)
        print("=" * 60)
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем (Ctrl+C)")
        orchestrator.stop_mcp_servers()
    except Exception as e:
        logger.exception("Критическая ошибка")
        print(f"\nКритическая ошибка: {e}")


if __name__ == "__main__":
    main()
