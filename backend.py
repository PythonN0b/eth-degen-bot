import asyncio
import aiohttp
import json
import ssl
import websockets
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from web3 import Web3

# ---------------- CONFIG ----------------
ALCHEMY_WS = "wss://eth-mainnet.g.alchemy.com/v2/dxucxS3Ch7PE5IyOU0ibp"
DEBUG = True
TEST_MODE = False

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2".lower()
UNISWAP_V2_FACTORY = Web3.to_checksum_address("0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f")
UNISWAP_V3_FACTORY = Web3.to_checksum_address("0x1F98431c8aD98523631AE4a59f267346ea31F984")

PAIR_CREATED_V2 = Web3.keccak(text="PairCreated(address,address,address,uint256)").hex()
POOL_CREATED_V3 = Web3.keccak(text="PoolCreated(address,address,uint24,int24,address)").hex()

w3 = Web3(Web3.WebsocketProvider(ALCHEMY_WS))
seen_tokens = set()
alerts_queue = asyncio.Queue()

# FastAPI
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- Socials / Safety ----------------
async def fetch_socials(token, session):
    try:
        async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}", timeout=10) as r:
            data = await r.json()
            pair = next((p for p in data.get("pairs", []) if p.get("chainId") == "ethereum"), None)
            if not pair or not pair.get("info"):
                return "No Twitter","No TG","No website"
            info = pair["info"]
            socials = info.get("socials", [])
            websites = info.get("websites", [])
            twitter = next((s["url"] for s in socials if "twitter.com" in s.get("url","") or "x.com" in s.get("url","")), "No Twitter")
            tg = next((s["url"] for s in socials if "t.me" in s.get("url","")), "No TG")
            web = websites[0]["url"] if websites else "No website"
            return twitter, tg, web
    except: return "Failed","Failed","Failed"

async def get_safety(token, session):
    try:
        async with session.get(f"https://tokensniffer.com/api/v2/token/ethereum/{token}", timeout=8) as r:
            if r.status != 200: return "Check failed"
            data = await r.json()
            if data.get("is_honeypot"): return "HONEYPOT"
            score = data.get("score",0)
            tax = max(data.get("buy_tax",0), data.get("sell_tax",0),0)
            if score >= 82 and tax <=15: return "SAFE"
            if tax>25: return "HIGH TAX"
            if score<50: return "SCAM RISK"
            return "MEDIUM"
    except: return "UNKNOWN"

async def get_pair(token, session):
    try:
        async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}", timeout=12) as r:
            data = await r.json()
            pairs = [p for p in data.get("pairs",[]) if p.get("chainId")=="ethereum"]
            if not pairs and TEST_MODE:
                return {"baseToken":{"name":"Unnamed","symbol":"???"},"liquidity":{"usd":0},"fdv":0,"volume":{"m5":0},"pairAddress":"N/A","info":{}}
            if not pairs: return None
            return max(pairs, key=lambda x: x.get("liquidity",{}).get("usd",0) or 0)
    except: return None

# ---------------- WebSocket Watcher ----------------
async def watcher():
    subscription = {"jsonrpc":"2.0","id":1,"method":"eth_subscribe","params":["logs",{"address":[UNISWAP_V2_FACTORY,UNISWAP_V3_FACTORY]}]}
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                async with websockets.connect(ALCHEMY_WS, ping_interval=20, ping_timeout=60, ssl=ssl_context) as ws:
                    print("🔴 LIVE ON ETH MAINNET")
                    await ws.send(json.dumps(subscription))
                    async for message in ws:
                        data = json.loads(message)
                        if "params" not in data: continue
                        log = data["params"]["result"]
                        topics = log.get("topics",[])
                        token = None

                        if topics and len(topics)>=3:
                            if topics[0]==PAIR_CREATED_V2:
                                t0 = "0x"+topics[1][-40:]
                                t1 = "0x"+topics[2][-40:]
                                token = t1 if t0.lower()==WETH else t0
                            elif topics[0]==POOL_CREATED_V3:
                                raw = log.get("data","")
                                t0_hex = raw[26:66].lower()
                                t1_hex = raw[86:126].lower()
                                t0 = "0x"+t0_hex[-40:]
                                t1 = "0x"+t1_hex[-40:]
                                token = t1 if t0.lower()==WETH else t0

                        if not token: continue
                        token = token.lower()
                        if token in seen_tokens: continue
                        seen_tokens.add(token)

                        pair = await get_pair(token, session)
                        twitter, tg_url, web = await fetch_socials(token, session)
                        safety = await get_safety(token, session)

                        alert = {
                            "token": token,
                            "pair": pair,
                            "twitter": twitter,
                            "telegram": tg_url,
                            "web": web,
                            "safety": safety
                        }
                        await alerts_queue.put(alert)

            except Exception as e:
                print(f"Reconnect: {e} | retrying in 3s...")
                await asyncio.sleep(3)

# ---------------- WebSocket API for Frontend ----------------
@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        alert = await alerts_queue.get()
        await websocket.send_json(alert)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    import uvicorn
    loop = asyncio.get_event_loop()
    loop.create_task(watcher())
    uvicorn.run(app, host="0.0.0.0", port=8000)
