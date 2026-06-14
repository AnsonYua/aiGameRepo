# GCG Replay Review Board

Local website for stepping through a `gamePlay.yaml` replay snapshot by snapshot.

## Run

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/reviewboard
python3 server.py --host 127.0.0.1 --port 5178
```

Open:

```text
http://127.0.0.1:5178
```

By default it loads:

```text
/Users/hello/Desktop/cardAI/gcgV2/out/game_20260614_124140_337599/gamePlay.yaml
```

To review another replay:

```bash
python3 server.py --replay /path/to/gamePlay.yaml
```

## Notes

- The board renders each event's `features` snapshot.
- Hidden zones are shown as face-down/count-only cards.
- Card ids such as `st01/ST01-008` map to `st01/ST01-008.png`.
- `EX-BASE` maps to `st01/EXB-001.png`.
