import asyncio
import json
from collections import deque
from typing import Deque, List, Optional

import websockets

from .actions import Action, CallAction, CheckAction, FoldAction, RaiseAction
from .config import (
    ACTION_REQUEST_RETRIES,
    ACTION_REQUEST_TIMEOUT,
    CONNECT_RETRIES,
    CONNECT_TIMEOUT,
    ENFORCE_GAME_CLOCK,
    PLAYER_LOG_SIZE_LIMIT,
    READY_CHECK_RETRIES,
    READY_CHECK_TIMEOUT,
    STARTING_GAME_CLOCK,
)


class Client:
    def __init__(
        self, name: str, websocket_uri: str, auth_token: Optional[str] = None
    ) -> None:
        self.name = name
        self.websocket_uri = websocket_uri
        self.auth_token = auth_token
        self.game_clock = STARTING_GAME_CLOCK
        self.bankroll = 0
        self.websocket = None
        self.log = deque()
        self.log_size = 0

    async def connect(self) -> None:
        for attempt in range(CONNECT_RETRIES):
            try:
                self.websocket = await asyncio.wait_for(
                    websockets.connect(self.websocket_uri),
                    timeout=CONNECT_TIMEOUT,
                )
                print(f"Connected to {self.websocket_uri}")
                return
            except (
                websockets.exceptions.InvalidURI,
                websockets.exceptions.InvalidHandshake,
            ):
                raise RuntimeError(f"Invalid WebSocket URI: {self.websocket_uri}")
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                if attempt < CONNECT_RETRIES - 1:
                    await asyncio.sleep(CONNECT_TIMEOUT)
                else:
                    raise RuntimeError(
                        f"Failed to connect to {self.websocket_uri} after {CONNECT_RETRIES} attempts"
                    )

    async def check_ready(self, player_names: List[str]) -> bool:
        request = {"ready_check": {"player_names": player_names}}
        for attempt in range(READY_CHECK_RETRIES):
            try:
                await asyncio.wait_for(
                    self.websocket.send(json.dumps(request)),
                    timeout=READY_CHECK_TIMEOUT,
                )
                response = await asyncio.wait_for(
                    self.websocket.recv(), timeout=READY_CHECK_TIMEOUT
                )
                response_data = json.loads(response)
                return response_data["ready"]
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                if attempt < READY_CHECK_RETRIES - 1:
                    await asyncio.sleep(READY_CHECK_TIMEOUT)
                else:
                    print(f"Bot {self.name} is not ready")
                    return False

    async def request_action(
        self, player_hand: List[str], board_cards: List[str], new_actions: Deque[Action]
    ) -> Optional[Action]:
        request = {
            "request_action": {
                "game_clock": self.game_clock,
                "player_hand": player_hand,
                "board_cards": board_cards,
                "new_actions": self._convert_actions_to_json(new_actions),
            }
        }
        for attempt in range(ACTION_REQUEST_RETRIES):
            try:
                await asyncio.wait_for(
                    self.websocket.send(json.dumps(request)),
                    timeout=ACTION_REQUEST_TIMEOUT,
                )
                response = await asyncio.wait_for(
                    self.websocket.recv(), timeout=ACTION_REQUEST_TIMEOUT
                )
                response_data = json.loads(response)
                action = self._convert_json_to_action(response_data)
                if ENFORCE_GAME_CLOCK:
                    self.game_clock = response_data.get("game_clock", self.game_clock)
                    if self.game_clock <= 0:
                        raise TimeoutError("Game clock has run out")
                return action
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                if attempt < ACTION_REQUEST_RETRIES - 1:
                    await asyncio.sleep(ACTION_REQUEST_TIMEOUT)
                else:
                    print("An error occurred during action request")
                    return None

    async def end_round(
        self,
        player_hand: List[str],
        opponent_hand: List[str],
        board_cards: List[str],
        new_actions: Deque[Action],
        delta: int,
        is_match_over: bool,
    ) -> None:
        request = {
            "end_round": {
                "player_hand": player_hand,
                "opponent_hand": opponent_hand,
                "board_cards": board_cards,
                "new_actions": self._convert_actions_to_json(new_actions),
                "delta": delta,
                "is_match_over": is_match_over,
            }
        }
        try:
            await self.websocket.send(json.dumps(request))
            response = await self.websocket.recv()
            response_data = json.loads(response)
            new_logs = response_data.get("logs", [])
            for log_entry in new_logs:
                entry_bytes = log_entry.encode("utf-8")
                entry_size = len(entry_bytes)
                if self.log_size + entry_size <= PLAYER_LOG_SIZE_LIMIT:
                    self.log.append(log_entry)
                    self.log_size += entry_size
                else:
                    if self.log_size < PLAYER_LOG_SIZE_LIMIT:
                        self.log.append(
                            "Log size limit reached. No further entries will be added."
                        )
                        self.log_size = PLAYER_LOG_SIZE_LIMIT
                    break
        except websockets.exceptions.ConnectionClosed:
            print("An error occurred during end round")

    async def close(self) -> None:
        if self.websocket:
            await self.websocket.close()

    def _convert_actions_to_json(self, actions: Deque[Action]) -> List[dict]:
        json_actions = []
        while actions:
            action = actions.popleft()
            json_action = self._convert_action_to_json(action)
            if json_action:
                json_actions.append(json_action)
        return json_actions

    @staticmethod
    def _convert_json_to_action(json_action: dict) -> Optional[Action]:
        action_type = json_action.get("action")
        if action_type == "FOLD":
            return FoldAction()
        elif action_type == "CALL":
            return CallAction()
        elif action_type == "CHECK":
            return CheckAction()
        elif action_type == "RAISE":
            amount = json_action.get("amount")
            if amount is not None:
                return RaiseAction(amount=amount)
        return None

    @staticmethod
    def _convert_action_to_json(action: Action) -> Optional[dict]:
        if isinstance(action, FoldAction):
            return {"action": "FOLD"}
        elif isinstance(action, CallAction):
            return {"action": "CALL"}
        elif isinstance(action, CheckAction):
            return {"action": "CHECK"}
        elif isinstance(action, RaiseAction):
            return {"action": "RAISE", "amount": action.amount}
        else:
            return None
