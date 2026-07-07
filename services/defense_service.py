from data.wnba.defenses import DEFENSE_DATABASE


class DefenseService:

    @staticmethod
    def get_profile(team: str):
        return DEFENSE_DATABASE.get(team)