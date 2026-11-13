# Running with Docker

You don't need Python installed. You need **Docker Desktop** (Windows / Mac) or Docker Engine (Linux).

## 1. Get the code

```bash
git clone https://github.com/xuantung9999-create/Market-Making-ASv2.git
cd Market-Making-ASv2
```

## 2. Open the dashboard

```bash
docker compose up dashboard
```

Then open **http://localhost:8000/dashboard/index.html**. Stop with `Ctrl+C`.

The first run builds the image (2–4 minutes). Later runs start in seconds.

## 3. Other things you can do

| What | Command |
|---|---|
| Run the test suite | `docker compose run --rm tests` |
| Record live Binance order books (runs in background) | `docker compose --profile live up -d recorder` |
| Stop the recorder | `docker compose --profile live down` |
| Recorder logs | `docker compose logs -f recorder` |
| Testnet trader (needs `.env` with testnet keys, see README) | `docker compose --profile live up testnet` |
| Run any script | `docker compose run --rm mm module scripts.plot_quotes` |
| Shell inside the container | `docker compose run --rm mm shell` |
| List commands | `docker compose run --rm mm help` |
| Rebuild after pulling new code | `docker compose build` |

The recorder reads the coins from `config/candidates.txt`. To pick your own:
`docker compose run --rm mm recorder --symbols BTCUSDT,ETHUSDT`

## Where files go

- `data/` holds downloaded and recorded market data. It is **not** in git (too large); it fills up when you run downloads or the recorder.
- `results/` holds backtest output that the dashboard reads.

Both folders are shared between your computer and the container, so anything the container writes appears in your project folder.

## Without compose

```bash
docker build -t mm-as .
docker run --rm -p 8000:8000 mm-as                    # dashboard
docker run --rm mm-as test                            # tests
docker run --rm -v "$PWD/data:/app/data" mm-as recorder
```

## Troubleshooting

- **Port 8000 is busy:** change `"8000:8000"` to `"8080:8000"` in `docker-compose.yml` and open port 8080.
- **Linux: "Permission denied" writing to data/ or results/:** the container runs as user id 1000. Run `sudo chown -R 1000:1000 data results` once.
- **Recorder can't connect:** Binance blocks some countries (including the US). Use a network where binance.com works.

This is research code. It does not place real orders.
