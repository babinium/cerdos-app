# 🐷 Cerdos App — Tragamonedas Porcina

Tragamonedas de 3 carretes con temática de cerdos especuladores.

## Cómo funciona

1. Conectá tu wallet (Phantom/Solflare)
2. Si tenés tokens CERDOS, jugá en modo REAL (1 CERDO por giro)
3. Sin wallet: modo PRUEBA gratis
4. ¡3 íconos iguales = ganás!

### Multiplicadores
| Ícono | Premio |
|-------|--------|
| 🐟 Mojarra | x1 |
| 🦈 Tiburón | x5 |
| 🐋 Ballena | x15 |
| 🐷 Cerdo | x40 |

## Estructura

- `index.html` — Frontend vanilla (HTML/CSS/JS + Solana Web3.js)
- `backend.py` — Backend Flask (maneja apuestas y pago de premios)
- `*.jpg` — Íconos de los carretes
- `*.mp3` — Sonidos (giro y pago)

## Deploy

El backend corre en un VPS con túnel Cloudflare. El frontend se sirve desde el mismo backend.
