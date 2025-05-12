import requests
import psycopg2
import time
from datetime import datetime, timedelta
from telegram import Bot
import asyncio


# Telegram bot token
TELEGRAM_BOT_TOKEN = ""
# Telegram chat ID
TELEGRAM_CHAT_ID = ""
# Etherscan API key
ETHERSCAN_API_KEY = ""
# Contract address
CONTRACT_ADDRESS = ""
# Rate limit settings
RATE_LIMIT = 5  # 5 requests per minute
RATE_LIMIT_INTERVAL = 60  # 1 minute in seconds
# Database connection settings
DB_HOST = "localhost"
DB_USER = "your_user_name"
DB_PASSWORD = "your_db_password"
DB_NAME = "your_db_name"


class RateLimiter:
    def __init__(self, rate_limit, interval):
        self.rate_limit = rate_limit
        self.interval = interval
        self.tokens = rate_limit
        self.last_refill_time = time.time()

    def refill_tokens(self):
        now = time.time()
        time_passed = now - self.last_refill_time
        tokens_to_add = int(time_passed / self.interval) * self.rate_limit
        self.tokens = min(self.tokens + tokens_to_add, self.rate_limit)
        self.last_refill_time = now

    def get_token(self):
        now = time.time()
        time_since_refill = now - self.last_refill_time
        tokens_to_refill = int(time_since_refill / self.interval) * self.rate_limit
        self.tokens = min(self.tokens + tokens_to_refill, self.rate_limit)
        if self.tokens > 0:
            self.tokens -= 1
            return True
        else:
            return False

rate_limiter = RateLimiter(rate_limit=RATE_LIMIT, interval=RATE_LIMIT_INTERVAL)

def fetch_transactions(start_block=None):
    rate_limiter.refill_tokens()
    if rate_limiter.get_token():
        if start_block is None:
            url = f"https://api.etherscan.io/api?module=account&action=txlist&address={CONTRACT_ADDRESS}&startblock=0&endblock=99999999&apikey={ETHERSCAN_API_KEY}"
        else:
            url = f"https://api.etherscan.io/api?module=account&action=txlist&address={CONTRACT_ADDRESS}&startblock={start_block}&endblock=99999999&apikey={ETHERSCAN_API_KEY}"
        
        print('Request URL:', url)  # Print URL for debugging
        response = requests.get(url)
        print('Response:', response.json())  # Print response for debugging
        data = response.json()
        return data['result']
    else:
        print("Rate limit exceeded. Waiting for next token refill.")
        return None

def fetch_logs(from_block, to_block):
    rate_limiter.refill_tokens()
    if rate_limiter.get_token():
        url = f"https://api.etherscan.io/api?module=logs&action=getLogs&address={CONTRACT_ADDRESS}&fromBlock={from_block}&toBlock={to_block}&topic0=0xe689c8111f40a171596b9d81ac47c6fe406d2297392957c5126c2f7448c58694&apikey={ETHERSCAN_API_KEY}"
        print('Request URL:', url)  # Print URL for debugging
        response = requests.get(url)
        print('Response:', response.json())  # Print response for debugging
        return response.json()['result']
    else:
        print("Rate limit exceeded. Waiting for next token refill.")
        return None
    
def decode_hex_string(hex_string):
    # Remove the leading "0x" if present and split the string into 32-character chunks
    chunks = [hex_string[i:i+32] for i in range(2, len(hex_string), 32)]
    
    decoded_values = []
    
    # Convert each chunk from hexadecimal to decimal
    for chunk in chunks:
        decoded_values.append(int(chunk, 16))
    
    return decoded_values

def process_logs(response_logs):
    eth_to_aix_exchange_rate = 1000  # Hypothetical exchange rate: 1 ETH = 1000 AIX
    wei_to_eth_conversion_factor = 10**18  # Conversion factor from wei to ETH
    
    # Initialize daily sum object
    daily_sum = {
        'aix_processed': 0,
        'aix_distributed': 0,
        'eth_bought': 0,
        'eth_distributed': 0
    }

    # current_time = datetime.now()
    # last_24_hours = current_time - timedelta(hours=24)

    for log in response_logs:
        decoded_values = decode_hex_string(log['data'])
        inputAixAmount = decoded_values[1]
        distributedAixAmount = decoded_values[3]
        swappedEthAmount = decoded_values[5]
        distributedEthAmount = decoded_values[7]
        swappedEthAmount_ETH = swappedEthAmount / wei_to_eth_conversion_factor
        distributedEthAmount_ETH = distributedEthAmount / wei_to_eth_conversion_factor

        # Convert AIX amounts to real values
        inputAixAmount_real = inputAixAmount / eth_to_aix_exchange_rate
        distributedAixAmount_real = distributedAixAmount / eth_to_aix_exchange_rate

        # Add the values to daily sum if within the last 24 hours
        # log_time = datetime.fromtimestamp(int(log['timeStamp']))
        # if log_time >= last_24_hours:
        daily_sum['aix_processed'] += inputAixAmount_real
        daily_sum['aix_distributed'] += distributedAixAmount_real
        daily_sum['eth_distributed'] += distributedEthAmount_ETH
        daily_sum['eth_bought'] += swappedEthAmount_ETH

        # Print the decoded values
        print("inputAixAmount (AIX):", inputAixAmount_real)
        print("distributedAixAmount (AIX):", distributedAixAmount_real)
        print("swappedEthAmount (ETH):", swappedEthAmount_ETH)
        print("distributedEthAmount (ETH):", distributedEthAmount_ETH)
    print(daily_sum)
    return daily_sum


def insert_transactions_to_db(transactions):
    try:
        connection = psycopg2.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME
        )
        cursor = connection.cursor()
        for tx in transactions:
            cursor.execute("INSERT INTO transactions (tx_hash, block_number) VALUES (%s, %s)", (tx['hash'], tx['blockNumber']))
        connection.commit()
        connection.close()
        print("Transactions inserted into the database successfully.")
    except psycopg2.Error as e:
        print("Error inserting transactions into the database:", e)


async def send_report(daily_sum):
    report_text = f"Daily $AIX Stats:\n" \
                  f"    - First TX: {datetime.now() - timedelta(hours=24)}\n" \
                  f"    - Last TX: {datetime.now()}\n" \
                  f"    - AIX processed: {daily_sum['aix_processed']}\n" \
                  f"    - AIX distributed: {daily_sum['aix_distributed']}\n" \
                  f"    - ETH bought: {daily_sum['eth_bought']}\n" \
                  f"    - ETH distributed: {daily_sum['eth_distributed']}\n"

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=report_text)

async def main():
    while True:
        transactions = fetch_transactions()
        if transactions:
            latest_block_number = max(int(tx['blockNumber']) for tx in transactions)

            # Calculate the block numbers for the last 24 hours
            last_24_hours_block = max(0, latest_block_number - 5760)  # Assuming 15 seconds per block

            # Fetch logs for the last 24 hours
            logs = fetch_logs(last_24_hours_block, latest_block_number)
            if logs:
                # Decode logs and process the data accordingly
                log_results = process_logs(logs)
                await send_report(log_results)
        await asyncio.sleep(14400)  # Sleep for 4 hours (4 hours * 60 minutes * 60 seconds)

if __name__ == "__main__":
    asyncio.run(main())
