import asyncio
import json
import time
from collections import deque
from typing import Deque, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

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
    """
    Represents a client that communicates with a poker bot using WebSocket.
    """

    def __init__(
        self, name: str, websocket_uri: str, auth_token: Optional[str] = None
    ) -> None:
        """
        Initializes a new instance of the Client class.

        Args:
            name (str): The name of the poker bot.
            websocket_uri (str): The URI of the WebSocket server.
            auth_token (Optional[str]): An optional authentication token.
        """
        self.name = name
        self.websocket_uri = websocket_uri
        self.auth_token = auth_token
        self.game_clock = STARTING_GAME_CLOCK
        self.bankroll = 0
        self.websocket = None
        self.log = deque()
        self.log_size = 0

    async def connect(self) -> None:
        """
        Connects to the WebSocket server with retries.
        """
        for attempt in range(CONNECT_RETRIES):
            try:
                self.websocket = await asyncio.wait_for(
                    websockets.connect(self.websocket_uri), timeout=CONNECT_TIMEOUT
                )
                print(f"Connected to {self.websocket_uri}")
                return
            except (InvalidURI, InvalidHandshake):
                raise RuntimeError(f"Invalid WebSocket URI: {self.websocket_uri}")
            except (asyncio.TimeoutError, ConnectionClosed):
                if attempt < CONNECT_RETRIES - 1:
                    await asyncio.sleep(CONNECT_TIMEOUT)
                else:
                    raise RuntimeError(
                        f"Failed to connect to {self.websocket_uri} after {CONNECT_RETRIES} attempts"
                    )

    async def check_ready(self, player_names: List[str]) -> bool:
        """
        Checks if the poker bot is ready.

        Args:
            player_names (List[str]): The list of player names.

        Returns:
            bool: True if the bot is ready, False otherwise.
        """
        request = {"ready_check": {"player_names": player_names}}
        print(f"Sending ready check request: {request}")
        for attempt in range(READY_CHECK_RETRIES):
            try:
                await asyncio.wait_for(
                    self.websocket.send(json.dumps(request)),
                    timeout=READY_CHECK_TIMEOUT,
                )
                print(f"Ready check request sent for {self.name}")
                response = await asyncio.wait_for(
                    self.websocket.recv(), timeout=READY_CHECK_TIMEOUT
                )
                print(f"Ready check response received for {self.name}: {response}")
                response_data = json.loads(response)
                return response_data["ready"]
            except (asyncio.TimeoutError, ConnectionClosed):
                if attempt < READY_CHECK_RETRIES - 1:
                    print(
                        f"Ready check attempt {attempt + 1} failed for {self.name}. Retrying..."
                    )
                    await asyncio.sleep(READY_CHECK_TIMEOUT)
                else:
                    print(
                        f"Bot {self.name} is not ready after {READY_CHECK_RETRIES} attempts"
                    )
                    return False

    async def request_action(
        self, player_hand: List[str], board_cards: List[str], new_actions: Deque[Action]
    ) -> Optional[Action]:
        """
        Requests an action from the poker bot.

        Args:
            player_hand (List[str]): The player's hand.
            board_cards (List[str]): The board cards.
            new_actions (Deque[Action]): The new actions since the last request.

        Returns:
            Optional[Action]: The action returned by the bot, or None if an error occurred.
        """
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
                start_time = time.perf_counter()

                await asyncio.wait_for(
                    self.websocket.send(json.dumps(request)),
                    timeout=ACTION_REQUEST_TIMEOUT,
                )
                response = await asyncio.wait_for(
                    self.websocket.recv(), timeout=ACTION_REQUEST_TIMEOUT
                )

                end_time = time.perf_counter()
                duration = end_time - start_time

                response_data = json.loads(response)
                action = self._convert_json_to_action(response_data)

                if ENFORCE_GAME_CLOCK:
                    self.game_clock -= duration
                    if self.game_clock <= 0:
                        raise TimeoutError("Game clock has run out")

                return action
            except (asyncio.TimeoutError, ConnectionClosed):
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
        """
        Notifies the poker bot that the round has ended.

        Args:
            player_hand (List[str]): The player's hand.
            opponent_hand (List[str]): The opponent's hand.
            board_cards (List[str]): The board cards.
            new_actions (Deque[Action]): The new actions since the last request.
            delta (int): The change in the player's bankroll.
            is_match_over (bool): Indicates whether the match is over.
        """
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
                    # Limit the size of the player's log to avoid excessive memory usage
                    if self.log_size < PLAYER_LOG_SIZE_LIMIT:
                        self.log.append(
                            "Log size limit reached. No further entries will be added."
                        )
                        self.log_size = PLAYER_LOG_SIZE_LIMIT
                    break
        except ConnectionClosed:
            print("An error occurred during end round")

    async def close(self) -> None:
        """
        Closes the WebSocket connection.
        """
        if self.websocket:
            await self.websocket.close()

    def _convert_actions_to_json(self, actions: Deque[Action]) -> List[dict]:
        """
        Converts a deque of Action objects to a list of JSON-serializable dictionaries.

        Args:
            actions (Deque[Action]): The deque of actions to convert.

        Returns:
            List[dict]: The list of JSON-serializable dictionaries.
        """
        json_actions = []
        while actions:
            action = actions.popleft()
            json_action = self._convert_action_to_json(action)
            if json_action:
                json_actions.append(json_action)
        return json_actions

    @staticmethod
    def _convert_json_to_action(json_action: dict) -> Optional[Action]:
        """
        Converts a JSON-serializable dictionary to an Action object.

        Args:
            json_action (dict): The JSON-serializable dictionary to convert.

        Returns:
            Optional[Action]: The corresponding Action object, or None if the action type is unknown.
        """
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
        """
        Converts an Action object to a JSON-serializable dictionary.

        Args:
            action (Action): The Action object to convert.

        Returns:
            Optional[dict]: The corresponding JSON-serializable dictionary, or None if the action type is unknown.
        """
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
