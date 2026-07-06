from repository.bet_repository import BetRepository

repo = BetRepository()

bets = repo.get_all()

print(bets)