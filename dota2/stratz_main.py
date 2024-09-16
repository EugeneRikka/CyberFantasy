import os
import json
import requests
import numpy as np
import pandas as pd
from styleframe import StyleFrame, Styler, utils

token = ''


def get_series(tournament_id, reload_data):
    if reload_data:
        url = f'https://api.stratz.com/api/v1/league/{tournament_id}/series'
        response = requests.get(url, headers={'Authorization': f'Bearer {token}'})

        series = {'series': response.json()}
        with open('parsed_data_stratz/series.json', 'w', encoding='utf8') as file:
            json.dump(series, file, indent=2)
    else:
        with open('parsed_data_stratz/series.json', 'r', encoding='utf8') as file:
            series = json.load(file)

    series['series'] = sorted(series['series'], key=lambda x: x['id'])

    return series


def get_match_info(match_id, reload_data):
    if reload_data and not os.path.exists(f'parsed_data_stratz/{match_id}.json'):
        url = f'https://api.stratz.com/api/v1/match/{match_id}'
        r = requests.get(url, headers={'Authorization': f'Bearer {token}'})
        match_info = r.json()

        with open(f'parsed_data_stratz/{match_id}.json', 'w', encoding='utf8') as file:
            json.dump(match_info, file, indent=2)

        return match_info
    else:
        with open(f'parsed_data_stratz/{match_id}.json', 'r', encoding='utf8') as file:
            return json.load(file)


def get_pro_players():
    with open('pro_players_stratz.json', 'r', encoding='utf8') as file:
        return json.load(file)


def create_fantasy_points_template(pro_players):
    fantasy_points = {'carry': {}, 'mid': {}, 'offlane': {}, 'support': {}}
    for player_name in pro_players:
        role = pro_players[player_name]['role']
        fantasy_points[role][player_name] = {
            'durations': [],
            'wins': [],
            'wins count': 0,
            'loses count': 0,
            'fantasy points': [],
            'points': [],
            'points details': [],
            'points details sum': dict()
        }

    return fantasy_points


def compute_fantasy_points(tournament_id, pro_players, reload_data, min_bound=0, max_bound=1e30):
    all_series = get_series(tournament_id, reload_data)

    fantasy_points = create_fantasy_points_template(pro_players)
    for series in all_series['series']:
        if not min_bound <= series['id'] < max_bound:
            continue

        maps_count = len(series['matches'])
        for match in series['matches']:
            match_id = match['id']

            try:
                match_info = get_match_info(match_id, reload_data)
            except Exception as e:
                print(f"Error: {e}")
                print(f"Match {match_id} has no saved data.")
            else:
                try:
                    for player in match_info['players']:
                        tower_count = 0
                        for building in player['stats']['farmDistributionReport']['buildings']:
                            if building['id'] == 0:
                                tower_count = building['count']
                                break

                        points_details = {
                            'kills': player['numKills'] * 1.5,
                            # 0 double damage 1 haste 2 illusion 3 invisibility 4 shield 5 gold 6 magic 7 water 8 wisdom 9 regen
                            'runes':  sum(1 for rune in player['stats']['runeEvents'] if rune['type'] in ['0', '1', '2', '3', '4', '6', '8', '9']) * 1.25,
                            'camps_stacked': player['stats']['campStackPerMin'][-1] * 1.5,
                            'obs_placed': sum(1 for ward in player['stats']['wardPlaced'] if ward['type'] == 0) * 1.5,
                            'last_hits': player['numLastHits'] * 0.015,
                            'courier_kills': len(player['stats']['courierKills']) * 2,
                            'towers_killed': tower_count * 2.5,
                            'roshans_killed': next((x['count'] for x in player['stats']['farmDistributionReport']['creepType'] if x['id'] == 133), 0) * 5,
                            'assists': player['numAssists'],
                            'teamfight_participation': 0, # player['teamfight_participation'] * 15,
                            'gold_per_min': player['goldPerMinute'] * 0.01,
                            'deaths': 15 - player['numDeaths']
                        }

                        player_name = player['steamAccount']['proSteamAccount']['name']

                        role = pro_players[player_name]['role']
                        player_info = fantasy_points[role][player_name]
                        player_info['durations'].append(match['durationSeconds'] / 60.0)
                        is_win = match['didRadiantWin'] == player['isRadiant']
                        player_info['wins'].append(is_win)
                        if is_win:
                            player_info['wins count'] += 1
                        else:
                            player_info['loses count'] += 1

                        player_info['points details'].append(points_details)
                        for key, value in points_details.items():
                            player_info['points details sum'][key] = player_info['points details sum'].get(key, 0) + value / maps_count

                        points_sum = round(sum(points_details.values()), 3)
                        player_info['fantasy points'].append(points_sum / maps_count)
                        player_info['points'].append(points_sum)

                except Exception as e:
                    print(f"Error: {e}")
                    print(f"Match {match_id} is not ready.")
                    # os.remove(f"parsed_data_stratz/{match_id}.json")

    for role in ['carry', 'mid', 'offlane', 'support']:
        fantasy_points[role] = {k: v for k, v in fantasy_points[role].items() if len(v) > 0}

    return fantasy_points


def post_calculate_points(fantasy_points, pro_players):
    for role in ['carry', 'mid', 'offlane', 'support']:
        for player_name, player_info in list(fantasy_points[role].items()):
            if len(player_info['fantasy points']) == 0:
                del fantasy_points[role][player_name]

        for player_name in fantasy_points[role]:
            player_info = fantasy_points[role][player_name]
            player_info['total points'] = np.round(np.sum(player_info['fantasy points']), 3)
            player_info['mean points per match'] = np.round(np.mean(player_info['points']), 3)

            player_info['mean points per win'] = 0
            player_info['mean points per lose'] = 0
            for i, points in enumerate(player_info['points']):
                if player_info['wins'][i]:
                    player_info['mean points per win'] += np.round(points / player_info['wins count'], 3)
                else:
                    player_info['mean points per lose'] += np.round(points / player_info['loses count'], 3)

            player_info['mean per cost'] = np.round(player_info['mean points per match'] / pro_players[player_name]['cost'], 3)
            player_info['mean duration'] = np.round(np.mean(player_info['durations']) / 60, 3)
            player_info['mean per duration'] = np.round(player_info['mean points per match'] / player_info['mean duration'], 3)
            player_info['match count'] = len(player_info['fantasy points'])


def dump_points_to_excel(writer, fantasy_points, sorting_key):
    for role in ['carry', 'mid', 'offlane', 'support']:
        if len(fantasy_points[role]) == 0:
            continue

        role_points = dict(sorted(fantasy_points[role].items(), key=lambda x: x[1][sorting_key], reverse=True))
        data = list()
        main_columns = ['total points', 'match count', 'mean points per match', 'mean points per win',
                        'mean points per lose', 'mean per cost', 'mean duration', 'mean per duration']
        details_columns = ['kills', 'runes', 'camps_stacked', 'obs_placed', 'last_hits', 'courier_kills',
                           'towers_killed', 'roshans_killed', 'assists', 'teamfight_participation', 'gold_per_min',
                           'deaths']
        columns = ['name'] + main_columns + details_columns
        for player_name in role_points:
            player_info = role_points[player_name]
            row = [player_name]
            for column_name in main_columns:
                row.append(player_info[column_name])
            for column_name in details_columns:
                row.append(player_info['points details sum'][column_name])
            data.append(row)
        df = pd.DataFrame(data, columns=columns)
        sf = StyleFrame(df)
        sf.A_FACTOR = 4
        sf.to_excel(writer, sheet_name=role, best_fit=columns)


def dump_captains_to_excel(writer, fantasy_points):
    captains_info = []
    for role in ['carry', 'mid', 'offlane', 'support']:
        for player_name in fantasy_points[role]:
            captains_info.append([player_name, fantasy_points[role][player_name]['total points'] * 2, role])
    captains_info = sorted(captains_info, key=lambda x: x[1], reverse=True)

    columns = ['name', 'points', 'role']
    df = pd.DataFrame(captains_info, columns=columns)
    sf = StyleFrame(df)
    sf.A_FACTOR = 4
    sf.to_excel(writer, sheet_name='captains rating', best_fit=columns)


def calculate_team_points(players_points, pro_players, players_names, captain_name):
    team_info = {'cost': 0, 'points': 0}
    positions_names = ['carry', 'mid', 'offlane', 'support', 'support']
    for player_index, player_name in enumerate(players_names):
        pos_name = positions_names[player_index]
        player_points = players_points[player_index]
        team_info[pos_name] = player_name
        team_info['cost'] += pro_players[player_name]['cost']
        if player_name == captain_name:
            team_info[pos_name] += ' (c)'
            player_points *= 2
        team_info['points'] += player_points

    return team_info


def dump_teams_rating_to_excel(writer, fantasy_points, pro_players, count, balance):
    teams_rating = []

    pos4_names = list(fantasy_points['support'])
    for pos1 in fantasy_points['carry']:
        for pos2 in fantasy_points['mid']:
            for pos3 in fantasy_points['offlane']:
                for pos4_index, pos4 in enumerate(pos4_names):
                    for pos5_index in range(pos4_index + 1, len(pos4_names)):
                        pos5 = pos4_names[pos5_index]
                        players_names = [pos1, pos2, pos3, pos4, pos5]
                        players_points = [fantasy_points['carry'][pos1]['total points'], fantasy_points['mid'][pos2]['total points'],
                                          fantasy_points['offlane'][pos3]['total points'], fantasy_points['support'][pos4]['total points'],
                                          fantasy_points['support'][pos5]['total points']]
                        for captain_name in players_names:
                            team_info = calculate_team_points(players_points, pro_players, players_names, captain_name)
                            teams_rating.append(team_info)

    teams_rating = sorted(teams_rating, key=lambda x: x['points'], reverse=True)
    columns = ['carry', 'mid', 'offlane', 'support', 'support', 'cost', 'points']
    top_teams_data = list()
    for team_info in teams_rating:
        if team_info['cost'] <= balance:
            row = list()
            for column_name in columns:
                row.append(team_info[column_name])
            top_teams_data.append(row)
            if len(top_teams_data) == count:
                break

    if len(top_teams_data):
        top_teams_df = pd.DataFrame(top_teams_data, columns=columns)
        sf_top_teams_df = StyleFrame(top_teams_df)
        sf_top_teams_df.A_FACTOR = 4
        sf_top_teams_df.to_excel(writer, sheet_name='Top teams', best_fit=columns)

    top_dream_teams_data = list()

    for team_info in teams_rating:
        row = list()
        for column_name in columns:
            row.append(team_info[column_name])
        top_dream_teams_data.append(row)
        if len(top_dream_teams_data) == count:
            break

    top_dream_teams_df = pd.DataFrame(top_dream_teams_data, columns=columns)
    sf_top_dream_teams_df = StyleFrame(top_dream_teams_df)
    sf_top_dream_teams_df.A_FACTOR = 4
    sf_top_dream_teams_df.to_excel(writer, sheet_name='Top dream teams', best_fit=columns)


def dump_day(name, tournament_id, reload_data, min_bound, max_bound, sort_key, balance):
    pro_players = get_pro_players()

    fantasy_points = compute_fantasy_points(tournament_id, pro_players, reload_data=reload_data, min_bound=min_bound, max_bound=max_bound)
    post_calculate_points(fantasy_points, pro_players)
    with pd.ExcelWriter(f'dota2_fantasy/{name}') as writer:
        dump_points_to_excel(writer, fantasy_points, sort_key)
        dump_captains_to_excel(writer, fantasy_points)
        # dump_teams_rating_to_excel(writer, fantasy_points, pro_players, count=1000, balance=balance)


def main():
    tournament_id = 16881  # riyadh 2024
    first_day = 1
    max_bound = 9999999999

    dump_day('test.xlsx', tournament_id, True, first_day, max_bound, 'total points', 100)


if __name__ == '__main__':
    main()
