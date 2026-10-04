# Portfolio Risk Intelligence

The Portfolio Intelligence panel evaluates **pending paid entries** as one exposure set. Paper cards are counted separately and do not consume paid stake. Player, team, game, stat, direction, provider, and market rows show the number of cards and the full wager exposed to that factor. These full-wager exposures are not additive. Sport concentration instead divides each mixed-sport card's wager equally across its distinct sports, so sport stake shares sum to at most 100% of identified stake.

Concentration Risk is deterministic:

- **HIGH**: an exact-market, player-bankroll, or open-wager limit is exceeded, or at least 70% of open stake is allocated to one sport across two or more cards.
- **MODERATE**: a market is repeated, another player/game entry limit is exceeded, or at least 50% of stake is allocated to one sport across two or more cards.
- **LOW**: neither threshold applies.

Market identity includes sport, game identity/time when known, player, stat, direction, and exact line. Missing game identity can make repeat detection less certain; the tracker must not present the overlap index as an empirical correlation or loss probability. The panel links to Results > Personal Edge for separate, descriptive settled-history context. Neither risk classification nor past hit rates guarantee future results.
