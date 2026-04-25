from nba_api.stats.static import players

players_list = players.get_active_players()

print("Active players:", len(players_list))
print(players_list[:10])
