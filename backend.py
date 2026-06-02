# Cerdos App — Backend + Frontend server
import json
import os
import logging
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.transaction import Transaction
from solders.commitment_config import CommitmentLevel
from solders.message import Message
from solders.hash import Hash
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solana.rpc.commitment import Confirmed
import struct
import requests as http_requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────
HOUSE_KEYPAIR_PATH = "/root/.config/solana/house-wallet.json"
RPC_URL = "https://mainnet.helius-rpc.com/?api-key=ef809e99-6099-412a-b731-3ce2cba78008"
CERDOS_MINT = Pubkey.from_string("CqJ5xawaraBqH5VPSQaCk7Dfei3aju3ry2UxfWkoGdKm")
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOC_TOKEN_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
FRONTEND_DIR = "/tmp/cerdos-app"

# ── Load house wallet ───────────────────────────────────
with open(HOUSE_KEYPAIR_PATH) as f:
    secret_bytes = bytes(json.load(f))
house_kp = Keypair.from_bytes(secret_bytes)
log.info(f"House wallet: {house_kp.pubkey()}")

house_ata, _ = Pubkey.find_program_address(
    [bytes(house_kp.pubkey()), bytes(TOKEN_PROGRAM), bytes(CERDOS_MINT)],
    ASSOC_TOKEN_PROGRAM
)
log.info(f"House ATA: {house_ata}")

client = Client(RPC_URL, commitment=Confirmed)


def derive_ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    ata, _ = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM), bytes(mint)],
        ASSOC_TOKEN_PROGRAM
    )
    return ata


def create_transfer_checked_instruction(source, mint, dest, owner, amount, decimals):
    data = struct.pack("<BQQ", 12, amount, decimals)
    keys = [
        AccountMeta(pubkey=source, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=dest, is_signer=False, is_writable=True),
        AccountMeta(pubkey=owner, is_signer=True, is_writable=False),
    ]
    return Instruction(program_id=TOKEN_PROGRAM, accounts=keys, data=data)


def send_token_transfer(dest_owner_pubkey: str, raw_amount: int) -> dict:
    dest_owner = Pubkey.from_string(dest_owner_pubkey)
    dest_ata = derive_ata(dest_owner, CERDOS_MINT)

    log.info(f"Transfer: {raw_amount} raw ({raw_amount / 100:.2f} CERDOS) -> {dest_owner_pubkey}")
    log.info(f"  Source ATA: {house_ata}")
    log.info(f"  Dest ATA:   {dest_ata}")

    ix = create_transfer_checked_instruction(
        house_ata, CERDOS_MINT, dest_ata, house_kp.pubkey(), raw_amount, 2
    )

    # Retry up to 3 times with fresh blockhash
    last_err = None
    for attempt in range(3):
        try:
            resp = client.get_latest_blockhash(commitment=Confirmed)
            bh = resp.value
            blockhash = Hash.from_string(str(bh.blockhash))

            msg = Message.new_with_blockhash(
                instructions=[ix], payer=house_kp.pubkey(), blockhash=blockhash
            )
            tx = Transaction.new_unsigned(msg)
            tx.sign([house_kp], blockhash)

            result = client.send_raw_transaction(bytes(tx), opts=TxOpts(
                skip_preflight=True,
                preflight_commitment=Confirmed,
            ))
            sig = str(result.value)
            log.info(f"  TX sent: {sig}")
            return {"success": True, "signature": sig}
        except Exception as e:
            last_err = str(e)
            log.warning(f"  Attempt {attempt + 1} failed: {last_err[:120]}")
            continue

    log.error(f"  All 3 attempts failed. Last error: {last_err}")
    return {"success": False, "error": last_err[:200]}


# ── Flask App ───────────────────────────────────────────
app = Flask(__name__)
CORS(app)


import base64
import random
from solders.transaction import VersionedTransaction
from solders.message import MessageV0


@app.route("/jugar", methods=["POST"])
def jugar():
    """Prepara una jugada: genera outcome aleatorio y tx de apuesta."""
    try:
        data = request.get_json(force=True)
        player_pubkey = data.get("player")
        if not player_pubkey:
            return jsonify({"success": False, "error": "Falta player"}), 400

        player_owner = Pubkey.from_string(player_pubkey)
        player_ata = derive_ata(player_owner, CERDOS_MINT)

        # Generar resultado aleatorio
        icons = [random.randint(0, 3) for _ in range(3)]

        # Construir tx de apuesta
        ix = create_transfer_checked_instruction(
            player_ata, CERDOS_MINT, house_ata, player_owner, 100, 2
        )

        resp = client.get_latest_blockhash(commitment=Confirmed)
        bh = resp.value
        blockhash = Hash.from_string(str(bh.blockhash))

        msg = Message.new_with_blockhash(
            instructions=[ix], payer=player_owner, blockhash=blockhash
        )
        tx = Transaction.new_unsigned(msg)

        tx_b64 = base64.b64encode(bytes(tx)).decode()

        return jsonify({
            "success": True,
            "icons": icons,
            "tx": tx_b64,
        })

    except Exception as e:
        log.error(f"Error en /jugar: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)[:200]}), 500


@app.route("/confirmar", methods=["POST"])
def confirmar():
    """Recibe tx firmada, la envía, y paga premio si ganó."""
    try:
        data = request.get_json(force=True)
        player_pubkey = data.get("player")
        signed_tx_b64 = data.get("signedTx")
        icons = data.get("icons")

        if not all([player_pubkey, signed_tx_b64, icons]):
            return jsonify({"success": False, "error": "Faltan datos"}), 400

        # Enviar tx de apuesta
        signed_bytes = base64.b64decode(signed_tx_b64)
        result = client.send_raw_transaction(signed_bytes, opts=TxOpts(
            skip_preflight=True, preflight_commitment=Confirmed
        ))
        bet_sig = str(result.value)
        log.info(f"Bet TX sent: {bet_sig}")

        # Verificar si ganó
        all_same = icons[0] == icons[1] == icons[2]
        prize_raw = 0
        prize_sig = None

        if all_same:
            multiplier = [1, 5, 15, 40][icons[0]]
            prize_raw = 100 * multiplier

            # Intentar pagar premio (con retry)
            pay_result = send_token_transfer(player_pubkey, prize_raw)
            if pay_result.get("success"):
                prize_sig = pay_result.get("signature")
            else:
                log.error(f"Pago de premio falló: {pay_result.get('error')}")

        return jsonify({
            "success": True,
            "win": all_same,
            "icons": icons,
            "prizeRaw": prize_raw,
            "betSig": bet_sig,
            "prizeSig": prize_sig,
        })

    except Exception as e:
        log.error(f"Error en /confirmar: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)[:200]}), 500


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


@app.route("/pagar", methods=["POST"])
def pagar():
    try:
        data = request.get_json(force=True)
        player = data.get("player")
        amount = data.get("amount")

        if not player or not amount:
            return jsonify({"success": False, "error": "Faltan player o amount"}), 400

        amount = int(amount)
        if amount <= 0:
            return jsonify({"success": False, "error": "Amount debe ser > 0"}), 400

        log.info(f"Pago solicitado: {amount} raw -> {player}")
        result = send_token_transfer(player, amount)
        return jsonify(result)

    except Exception as e:
        log.error(f"Error en /pagar: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)[:200]}), 500


@app.route("/balance", methods=["GET"])
def balance():
    """Verifica balance de CERDOS server-side (sin CORS)."""
    try:
        wallet = request.args.get("wallet")
        if not wallet:
            return jsonify({"error": "Falta wallet"}), 400
        
        body = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet,
                {"mint": "CqJ5xawaraBqH5VPSQaCk7Dfei3aju3ry2UxfWkoGdKm"},
                {"encoding": "jsonParsed"}
            ]
        }
        resp = http_requests.post(RPC_URL, json=body, timeout=15)
        data = resp.json()
        
        total = 0
        for acc in data.get("result", {}).get("value", []):
            total += int(acc["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
        
        return jsonify({"balance": total, "decimals": 2})
    except Exception as e:
        log.error(f"Error en /balance: {e}")
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/rpc", methods=["POST"])
def rpc_proxy():
    """Proxy JSON-RPC calls to Helius (evita CORS)."""
    try:
        data = request.get_json(force=True)
        resp = http_requests.post(RPC_URL, json=data, timeout=15)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        log.error(f"Error en /rpc: {e}")
        return jsonify({"jsonrpc": "2.0", "error": str(e)[:200], "id": 1}), 502


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "house": str(house_kp.pubkey()),
        "ata": str(house_ata),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8989))
    log.info(f"Iniciando en puerto {port} -> https://convinced-filed-success-defined.trycloudflare.com")
    app.run(host="0.0.0.0", port=port, debug=False)
