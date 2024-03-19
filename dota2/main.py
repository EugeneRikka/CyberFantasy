import os
import json
import requests
import numpy as np
import pandas as pd
from styleframe import StyleFrame


def get_matches(tournament_id, reload_data):
    if reload_data:
        # Retrieve matches data from the API
        url = f'https://api.opendota.com/api/leagues/{tournament_id}/matches'
        response = requests.get(url)
        matches = {'matches': response.json()}

        # Save matches data to a JSON file
        with open('parsed_data/matches.json', 'w', encoding='utf8') as file:
            json.dump(matches, file, indent=2)
    else:
        # Load matches data from the existing JSON file
        with open('parsed_data/matches.json', 'r', encoding='utf8') as file:
            matches = json.load(file)

    # Sort the matches data by match_id
    matches['matches'] = sorted(matches['matches'], key=lambda x: x['match_id'])

    return matches


def get_match_info(match_id, reload_data):
    if reload_data and not os.path.exists(f'parsed_data/{match_id}.json'):
        # Retrieve match information from the API
        r = requests.get(f'https://api.opendota.com/api/matches/{match_id}')
        match_info = r.json()

        # Save match information in a JSON file
        with open(f'parsed_data/{match_id}.json', 'w', encoding='utf8') as file:
            json.dump(match_info, file, indent=2)

        return match_info
    else:
        # Load match information from the existing JSON file
        with open(f'parsed_data/{match_id}.json', 'r', encoding='utf8') as file:
            return json.load(file)


def get_pro_players():
    with open('pro_players.json', 'r', encoding='utf8') as file:
        return json.load(file)


def create_fantasy_points_template(pro_players):
    fantasy_points = [dict() for _ in range(6)]
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


def calculate_series_counts(matches):
    series_counts = {}
    for match in matches['matches']:
        series_id = match['series_id']
        series_counts[series_id] = series_counts.get(series_id, 0) + 1
    return series_counts



def compute_fantasy_points(tournament_id, pro_players, reload_data, min_bound=0, max_bound=1e30):
    matches = get_matches(tournament_id, reload_data)

    # TODO: remove later, that's AR - TA series remake fix
    for match in matches['matches']:
        if match['match_id'] == 7378986342:
            matches['matches'].remove(match)
            break
    for match in matches['matches']:
        if match['match_id'] == 7378947046:
            match['series_id'] = 815377
            break

    fantasy_points = create_fantasy_points_template(pro_players)
    series_counts = calculate_series_counts(matches)
    for match in matches['matches']:
        match_id = match['match_id']
        series_id = match['series_id']

        if not min_bound <= match_id < max_bound:
            continue

        try:
            match_info = get_match_info(match_id, reload_data)
        except Exception as e:
            print(f"Error: {e}")
            print(f"Match {match_id} has no saved data.")
        else:
            try:
                for player in match_info['players']:
                    points_details = {}
                    points_details['kills'] = player['kills'] * 1.5
                    # 0 double damage 1 haste 2 illusion 3 invisibility 4 shield 5 gold 6 magic 7 water 8 wisdom 9 regen
                    runes_count = 0
                    for rune in player['runes']:
                        if rune in ['0', '1', '2', '3', '4', '6', '8', '9']:
                            runes_count += player['runes'][rune]
                    points_details['runes'] = runes_count * 1.25
                    points_details['camps_stacked'] = player['camps_stacked'] * 1.5
                    points_details['obs_placed'] = player['obs_placed'] * 1.5
                    points_details['last_hits'] = (player['lane_kills'] + player['neutral_kills'] + player['ancient_kills']) * 0.015
                    points_details['courier_kills'] = player['courier_kills'] * 2
                    points_details['towers_killed'] = player['towers_killed'] * 2.5
                    points_details['roshans_killed'] = player['roshans_killed'] * 5
                    points_details['assists'] = player['assists']
                    points_details['teamfight_participation'] = player['teamfight_participation'] * 15
                    points_details['gold_per_min'] = player['gold_per_min'] * 0.01
                    points_details['deaths'] = 15 - player['deaths']

                    player_name = player['name']
                    role = pro_players[player_name]['role']
                    player_info = fantasy_points[role][player_name]
                    player_info['durations'].append(match['duration'])
                    is_win = match['radiant_win'] == player['isRadiant']
                    player_info['wins'].append(is_win)
                    if is_win:
                        player_info['wins count'] += 1
                    else:
                        player_info['loses count'] += 1

                    player_info['points details'].append(points_details)
                    for key, value in points_details.items():
                        player_info['points details sum'][key] = player_info['points details sum'].get(key, 0) + value / series_counts[series_id]

                    points_sum = round(sum(points_details.values()), 3)
                    player_info['fantasy points'].append(points_sum / series_counts[series_id])
                    player_info['points'].append(points_sum)

            except Exception as e:
                print(f"Error: {e}")
                print(f"Match {match_id} is not ready.")
                os.remove(f"parsed_data/{match_id}.json")

    for role in range(1, 6):
        fantasy_points[role] = {k: v for k, v in fantasy_points[role].items() if len(v) > 0}

    return fantasy_points


def post_calculate_points(fantasy_points, pro_players):
    for role in range(1, 6):
        for player_name, player_info in list(fantasy_points[role].items()):
            if len(player_info['fantasy points']) == 0:
                del fantasy_points[role][player_name]

        for player_name in fantasy_points[role]:
            player_info = fantasy_points[role][player_name]
            player_info['day points'] = np.round(np.sum(player_info['fantasy points']), 3)
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
    for role in range(1, 6):
        if len(fantasy_points[role]) == 0:
            continue

        role_points = dict(sorted(fantasy_points[role].items(), key=lambda x: x[1][sorting_key], reverse=True))
        data = list()
        main_columns = ['day points', 'match count', 'mean points per match', 'mean points per win',
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
        sf.to_excel(writer, sheet_name=f'pos {role}', best_fit=columns)


def dump_captains_to_excel(writer, fantasy_points):
    captains_info = []
    for role in range(1, 6):
        for player_name in fantasy_points[role]:
            captains_info.append([player_name, fantasy_points[role][player_name]['day points'] * 2, role])
    captains_info = sorted(captains_info, key=lambda x: x[1], reverse=True)

    columns = ['name', 'points', 'role']
    df = pd.DataFrame(captains_info, columns=columns)
    sf = StyleFrame(df)
    sf.to_excel(writer, sheet_name='captains rating', best_fit=columns)


def calculate_team_points(players_points, pro_players, players_names, captain_name):
    team_info = {'cost': 0, 'points': 0}
    positions_names = ['carry', 'mid', 'offlane', 'sup1', 'sup2']
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

    pos4_names = list(fantasy_points[4])
    for pos1 in fantasy_points[1]:
        for pos2 in fantasy_points[2]:
            for pos3 in fantasy_points[3]:
                for pos4_index, pos4 in enumerate(pos4_names):
                    for pos5_index in range(pos4_index + 1, len(pos4_names)):
                        pos5 = pos4_names[pos5_index]
                        players_names = [pos1, pos2, pos3, pos4, pos5]
                        players_points = [fantasy_points[1][pos1]['day points'], fantasy_points[2][pos2]['day points'],
                                          fantasy_points[3][pos3]['day points'], fantasy_points[4][pos4]['day points'],
                                          fantasy_points[4][pos5]['day points']]
                        for captain_name in players_names:
                            team_info = calculate_team_points(players_points, pro_players, players_names, captain_name)
                            teams_rating.append(team_info)

    teams_rating = sorted(teams_rating, key=lambda x: x['points'], reverse=True)
    columns = ['carry', 'mid', 'offlane', 'sup1', 'sup2', 'cost', 'points']
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
    sf_top_dream_teams_df.to_excel(writer, sheet_name='Top dream teams', best_fit=columns)


def dump_day(name, tournament_id, reload_data, min_bound, max_bound, sort_key, balance):
    pro_players = get_pro_players()

    # change role groups
    for player_name in pro_players:
        role = pro_players[player_name]['role']
        if role == 5:
            pro_players[player_name]['role'] = 4

    fantasy_points = compute_fantasy_points(tournament_id, pro_players, reload_data=reload_data, min_bound=min_bound, max_bound=max_bound)
    post_calculate_points(fantasy_points, pro_players)
    with pd.ExcelWriter(name) as writer:
        dump_points_to_excel(writer, fantasy_points, sort_key)
        dump_captains_to_excel(writer, fantasy_points)
        dump_teams_rating_to_excel(writer, fantasy_points, pro_players, count=1000, balance=balance)


def main():
    tournament_id = 15728  # the international 2023
    first_day = 7378530387
    second_day = 7379995104
    third_day = 7381789226
    fourth_day = 7383689600
    fifth_day = 7391149823
    sixth_day = 7392908789
    seventh_day = 7394832000
    eighth_day = 7402531427
    ninth_day = 7404249421
    tenth_day = 7406129687
    max_bound = 9999999999

    dump_day('day10.xlsx', tournament_id, False, tenth_day, max_bound, 'day points', 140)
    # dump_day('overall.xlsx', tournament_id, False, first_day, max_bound, 'mean points per match', 100)
    # dump_day('playoff.xlsx', tournament_id, False, third_day, max_bound, 'mean points per match', 100)


if __name__ == '__main__':
    main()
