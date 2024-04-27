import os

# PARAMETERS TO CONTROL THE BEHAVIOR OF THE GAME ENGINE

# Player names
PLAYER_1_NAME = os.getenv("PLAYER_1_NAME", "all-in-bot")
PLAYER_2_NAME = os.getenv("PLAYER_2_NAME", "prob-bot")

# DNS names for player bots, retrieved from environment variables
PLAYER_1_DNS = os.getenv("PLAYER_1_DNS", "localhost:50051")
PLAYER_2_DNS = os.getenv("PLAYER_2_DNS", "localhost:50052")


# GAME PROGRESS IS RECORDED HERE
@staticmethod
def _get_unique_filename(base_filename):
    file_idx = 1
    filename, ext = os.path.splitext(base_filename)
    unique_filename = base_filename
    while os.path.exists(unique_filename):
        file_idx += 1
        unique_filename = f"{filename}_{file_idx}{ext}"
    return unique_filename


MATCH_ID = os.getenv("MATCH_ID", 0)
os.makedirs("logs", exist_ok=True)
GAME_LOG_TXT_FILENAME = os.path.join("logs", "engine_log.txt")
GAME_LOG_CSV_FILENAME = _get_unique_filename(os.path.join("logs", "engine_log.csv"))


def get_player_filename(player_name):
    player_log_dir = os.path.join("logs", player_name)
    os.makedirs(player_log_dir, exist_ok=True)
    return os.path.join(player_log_dir, "debug_log.txt")


# PLAYER_LOG_SIZE_LIMIT IS IN BYTES
PLAYER_LOG_SIZE_LIMIT = 1000000  # 1 MB

# STARTING_GAME_CLOCK AND TIMEOUTS ARE IN SECONDS
CONNECT_TIMEOUT = 4
CONNECT_RETRIES = 5
READY_CHECK_TIMEOUT = 0
READY_CHECK_RETRIES = 1
ACTION_REQUEST_TIMEOUT = 2
ACTION_REQUEST_RETRIES = 2
ENFORCE_GAME_CLOCK = True
STARTING_GAME_CLOCK = 300.0

# THE GAME VARIANT FIXES THE PARAMETERS BELOW
NUM_ROUNDS = 1000
STARTING_STACK = 400
BIG_BLIND = 2
SMALL_BLIND = 1
