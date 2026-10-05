# nfl-live

ESPN-style live NFL scoreboard for your terminal. Pure Python 3, no dependencies.

- Score cards in a grid that adapts to terminal width
- Live games pinned on top, then upcoming, then final
- Redraws in place; polls every 5s while games are live, 30s otherwise
- Recent scoring flagged with ▲ for 45 seconds

```
./nfl_live.py              # all games this week
./nfl_live.py --sunday     # only Sunday games
./nfl_live.py -i 3         # fixed refresh interval (seconds)
./nfl_live.py --once       # print once and exit
```

Data comes from ESPN's public (undocumented) scoreboard API, which may change without notice.
