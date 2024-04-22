import asyncio
import json

import websockets
from skeleton.actions import Action, CallAction, CheckAction, FoldAction, RaiseAction
from skeleton.bot import Bot
from skeleton.states import (
    BIG_BLIND,
    SMALL_BLIND,
    STARTING_STACK,
    GameState,
    RoundState,
    TerminalState,
)


class Runner:
    def __init__(self, pokerbot: Bot):
        self.pokerbot: Bot = pokerbot
        self.game_state = GameState(0, 0.0, 1)
        self.round_state = None
        self.round_flag = True

    async def handle_message(self, websocket, path):
        while True:
            try:
                message = await websocket.recv()
                request = json.loads(message)

                if "ready_check" in request:
                    response = await self.ReadyCheck(request["ready_check"])
                    await websocket.send(json.dumps(response))
                elif "request_action" in request:
                    response = await self.RequestAction(request["request_action"])
                    await websocket.send(json.dumps(response))
                elif "end_round" in request:
                    response = await self.EndRound(request["end_round"])
                    await websocket.send(json.dumps(response))
            except websockets.exceptions.ConnectionClosed:
                break

    async def ReadyCheck(self, request):
        return {"ready": True}

    async def RequestAction(self, request):
        self.game_state = GameState(
            self.game_state.bankroll,
            request["game_clock"],
            self.game_state.round_num,
        )

        if self.round_flag:
            self._new_round(request["player_hand"], request["board_cards"])
        else:
            self.round_state = RoundState(
                self.round_state.button,
                self.round_state.street,
                self.round_state.pips,
                self.round_state.stacks,
                self.round_state.hands,
                request["board_cards"],
                self.round_state.previous_state,
            )

        for action in request["new_actions"]:
            self.round_state = self.round_state.proceed(self._convert_action(action))

        active = self.round_state.button % 2
        observation = {
            "legal_actions": self.round_state.legal_actions(),
            "street": self.round_state.street,
            "my_cards": self.round_state.hands[0],
            "board_cards": list(self.round_state.board),
            "my_pip": self.round_state.pips[active],
            "opp_pip": self.round_state.pips[1 - active],
            "my_stack": self.round_state.stacks[active],
            "opp_stack": self.round_state.stacks[1 - active],
            "my_bankroll": self.game_state.bankroll,
            "min_raise": self.round_state.raise_bounds()[0],
            "max_raise": self.round_state.raise_bounds()[1],
        }
        try:
            action = self.pokerbot.get_action(observation)
        except Exception as e:
            self.pokerbot.log.append(f"Error raised: {e}")
        self.round_state = self.round_state.proceed(action)

        return self._convert_action_to_response(action)

    async def EndRound(self, request):
        if self.round_flag:
            self._new_round(request["player_hand"], request["board_cards"])
        if isinstance(self.round_state, TerminalState):
            self.round_state = self.round_state.previous_state
        hands = self.round_state.hands
        hands[1] = request["opponent_hand"]
        self.round_state = RoundState(
            button=self.round_state.button,
            street=self.round_state.street,
            pips=self.round_state.pips,
            stacks=self.round_state.stacks,
            hands=hands,
            board=self.round_state.board,
            previous_state=self.round_state.previous_state,
        )

        for action in request["new_actions"]:
            self.round_state = self.round_state.proceed(self._convert_action(action))

        deltas = [0, 0]
        deltas[self.active] = request["delta"]
        deltas[1 - self.active] = -request["delta"]
        self.round_state = TerminalState(deltas, self.round_state.previous_state)

        bot_logs = self.pokerbot.handle_round_over(
            self.game_state, self.round_state, self.active, request["is_match_over"]
        )

        self.game_state = GameState(
            bankroll=self.game_state.bankroll + request["delta"],
            game_clock=self.game_state.game_clock,
            round_num=self.game_state.round_num + 1,
        )

        self.round_flag = True

        return {"logs": bot_logs}

    def _convert_action_to_response(self, action: Action):
        if isinstance(action, FoldAction):
            return {"action": "FOLD"}
        elif isinstance(action, CallAction):
            return {"action": "CALL"}
        elif isinstance(action, CheckAction):
            return {"action": "CHECK"}
        elif isinstance(action, RaiseAction):
            return {"action": "RAISE", "amount": action.amount}

    def _convert_action(self, action):
        if action["action"] == "FOLD":
            return FoldAction()
        elif action["action"] == "CALL":
            return CallAction()
        elif action["action"] == "CHECK":
            return CheckAction()
        elif action["action"] == "RAISE":
            return RaiseAction(action["amount"])

    def _new_round(self, hand, board):
        self.round_state = RoundState(
            button=0,
            street=0,
            pips=[SMALL_BLIND, BIG_BLIND],
            stacks=[STARTING_STACK - SMALL_BLIND, STARTING_STACK - BIG_BLIND],
            hands=[hand, []],
            board=board,
            previous_state=None,
        )
        self.active = 0
        self.pokerbot.handle_new_round(self.game_state, self.round_state, self.active)
        self.round_flag = False


async def run_bot(pokerbot):
    runner = Runner(pokerbot)
    async with websockets.serve(runner.handle_message, "localhost", 8765):
        await asyncio.Future()


if __name__ == "__main__":
    pokerbot = Bot()
    asyncio.run(run_bot(pokerbot))
