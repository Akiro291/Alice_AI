#!/usr/bin/env python3
"""AI Agent Orchestrator - упрощенная рабочая версия"""
import json
import subprocess
import logging
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

LOG_FILE = Path(__file__).parent / "agent.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class AgentConfig:
    model_name: str = "qwen2.5:14b"  # Имя твоей модели в Ollama
    max_steps: int = 10

class AgentOrchestrator:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.current_step = 0
        self.mcp_servers = {}
        
    def load_mcp_config(self) -> Dict[str, Any]:
        cp = Path(__file__).parent / "mcp.json"
        if not cp.exists():
            logger.error("mcp.json не найден")
            return {}
        with open(cp, "r", encoding="utf-8") as f:
            return json.load(f)

    def start_mcp_servers(self):
        config = self.load_mcp_config()
        for server in config.get("servers", []):
            name = server.get("name")
            cmd = server.get("command")
            if cmd:
                try:
                    self.mcp_servers[name] = subprocess.Popen(
                        cmd.split(), 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE, 
                        text=True
                    )
                    logger.info(f"MCP {name} запущен")
                except Exception as e:
                    logger.error(f"Ошибка запуска {name}: {e}")

    def stop_mcp_servers(self):
        for name, p in self.mcp_servers.items():
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=5)
                logger.info(f"MCP {name} остановлен")

    def call_ollama(self, prompt: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["ollama", "run", self.config.model_name, prompt],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.error(f"Ollama error: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            logger.error("Ollama timeout")
            return None

    def parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        tool_calls = []
        # Ищем паттерны вроде "browser_navigate(url='...')"
        pattern = r'(\w+)\((.*?)\)'
        matches = re.findall(pattern, response)
        for match in matches:
            name = match[0]
            args_str = match[1]
            args = {}
            # Простой парсинг аргументов
            for arg in args_str.split(','):
                if '=' in arg:
                    k, v = arg.split('=', 1)
                    args[k.strip()] = v.strip().strip("'\"")
            tool_calls.append({"name": name, "args": args})
        return tool_calls

    def execute_tool_call(self, tool_call: Dict[str, Any]) -> str:
        name = tool_call["name"]
        args = tool_call["args"]
        logger.info(f"Вызов инструмента: {name} с аргументами {args}")
        
        # ЗДЕСЬ ДОЛЖНА БЫТЬ ЛОГИКА MCP, НО ПОКА ИМИТАЦИЯ
        if "windows" in name:
            return f"✅ Windows: {name} выполнено"
        elif "browser" in name or "playwright" in name:
            return f"✅ Browser: {name} выполнено"
        else:
            return f"⚠ Неизвестный инструмент: {name}"

    def run_cycle(self, task: str) -> str:
        self.start_mcp_servers()
        logger.info(f"Начало задачи: {task}")
        
        for step in range(1, self.config.max_steps + 1):
            logger.info(f"Шаг {step}/{self.config.max_steps}")
            
            prompt = f"Ты ИИ-агент. Задача: {task}. Если готово, напиши TERMINATE. Иначе вызови инструмент (например, browser_navigate(url='...'))."
            response = self.call_ollama(prompt)
            
            if not response:
                self.stop_mcp_servers()
                return "Ошибка: Ollama не отвечает"
            
            logger.info(f"Модель ответила: {response[:200]}...")
            
            if "TERMINATE" in response.upper():
                self.stop_mcp_servers()
                return f"✅ Задача выполнена: {response}"
            
            tool_calls = self.parse_tool_calls(response)
            if tool_calls:
                for tc in tool_calls:
                    result = self.execute_tool_call(tc)
                    logger.info(result)
            else:
                logger.info("Модель не вызвала инструменты")
        
        self.stop_mcp_servers()
        return "❌ Лимит шагов исчерпан"

def main():
    config = AgentConfig()
    orchestrator = AgentOrchestrator(config)
    
    print("="*60)
    print("AI AGENT ORCHESTRATOR")
    print("="*60)
    print(f"Модель: {config.model_name}")
    print(f"Лимит шагов: {config.max_steps}")
    print()
    
    task = input("Введите задачу: ").strip()
    if not task:
        print("Задача не введена")
        return
    
    try:
        result = orchestrator.run_cycle(task)
        print(f"\nРЕЗУЛЬТАТ: {result}")
    except KeyboardInterrupt:
        print("\nПрервано")
    finally:
        orchestrator.stop_mcp_servers()

if __name__ == "__main__":
    main()