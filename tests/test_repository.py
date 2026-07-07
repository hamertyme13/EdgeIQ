from repository.bet_repository import BetRepository


def test_repository_can_count_bets():
    repo = BetRepository()

    assert isinstance(repo.count(), int)
