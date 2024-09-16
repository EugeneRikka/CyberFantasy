import os
from pathlib import Path
import json
import requests
import numpy as np
import pandas as pd
from styleframe import StyleFrame, Styler, utils

import itertools


def get_matches(tournament_id, reload_data):
    if reload_data:
        # Retrieve matches data from the API
        url = f'https://api.opendota.com/api/leagues/{tournament_id}/matches'
        response = requests.get(url)
        matches = {'matches': response.json()}

        # Save matches data to a JSON file
        with open(f'parsed_data/{tournament_id}.json', 'w', encoding='utf8') as file:
            json.dump(matches, file, indent=2)
    else:
        # Load matches data from the existing JSON file
        with open(f'parsed_data/{tournament_id}.json', 'r', encoding='utf8') as file:
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


def get_pro_players(file_name: str):
    with open(file_name, 'r', encoding='utf8') as file:
        return json.load(file)


def create_fantasy_points_template(pro_players):
    fantasy_points = {'carry': {}, 'mid': {}, 'offlane': {}, 'support': {}}
    for player_name in pro_players:
        role = pro_players[player_name]['role']
        if 'save_as' in pro_players[player_name]:
            player_name = pro_players[player_name]['save_as']
        fantasy_points[role][player_name] = {
            'durations': [],
            'wins': [],
            'wins count': 0,
            'loses count': 0,
            'fantasy points': [],
            'points': [],
            'match points': '',
            'min points': 0,
            'max points': 0,
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


printed_id = {}
printed_names = {}


def compute_fantasy_points(tournament_id, pro_players, reload_data, min_bound=0, max_bound=1e30):
    account_id_mapping = {}
    for player_name in pro_players:
        account_id_mapping[pro_players[player_name]['account_id']] = player_name

    matches = get_matches(tournament_id, reload_data)

    fantasy_points = create_fantasy_points_template(pro_players)
    series_counts = calculate_series_counts(matches)
    for match in matches['matches']:
        match_id = match['match_id']
        series_id = match['series_id']
        if series_id == 903653:
            continue

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
                    # 0 double damage 1 haste 2 illusion 3 invisibility 4 shield 5 gold 6 magic 7 water 8 wisdom 9 regen
                    runes_count = 0
                    for rune in player['runes']:
                        if rune in ['0', '1', '2', '3', '4', '6', '8', '9']:
                            runes_count += player['runes'][rune]

                    points_details = {
                        'kills': player['kills'] * 1.5,
                        'runes': runes_count * 1.25,
                        'camps_stacked': player['camps_stacked'] * 1.5,
                        'obs_placed': player['obs_placed'] * 1.5,
                        'last_hits': (player['lane_kills'] + player['neutral_kills'] + player['ancient_kills']) * 0.015,
                        'courier_kills': player['courier_kills'] * 2,
                        'towers_killed': player['towers_killed'] * 2.5,
                        'roshans_killed': player['roshans_killed'] * 5,
                        'assists': player['assists'],
                        'teamfight_participation': player['teamfight_participation'] * 15,
                        'gold_per_min': player['gold_per_min'] * 0.01,
                        'deaths': 15 - player['deaths']
                    }

                    player_name = player['name']
                    if player_name is None:
                        account_id = player['account_id']
                        if account_id not in account_id_mapping:
                            if account_id not in printed_id:
                                printed_id[account_id] = ''
                                print(f'{account_id} skipped')

                            continue

                        player_name = account_id_mapping[account_id]

                    if player_name not in pro_players:
                        if player_name not in printed_names:
                            printed_names[player_name] = ''
                            print(f'{player_name} not in pro_players')

                        continue

                    role = pro_players[player_name]['role']

                    if 'save_as' in pro_players[player_name]:
                        player_name = pro_players[player_name]['save_as']
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
                    player_info['match points'] += '{0: <9}'.format(points_sum)

            except Exception as e:
                print(f"Error: {e}")
                print(f"Match {match_id} is not ready.")
                os.remove(f"parsed_data/{match_id}.json")

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
            player_info['min points'] = np.round(np.min(player_info['points']), 3)
            player_info['max points'] = np.round(np.max(player_info['points']), 3)

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


def dump_points_to_excel(writer, fantasy_points, pro_players, sorting_key):
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
        columns = ['name', 'team', 'cost'] + main_columns + details_columns
        for player_name in role_points:
            player_info = role_points[player_name]
            row = [player_name, pro_players[player_name]['team'], pro_players[player_name]['cost']]
            for column_name in main_columns:
                row.append(player_info[column_name])
            for column_name in details_columns:
                row.append(player_info['points details sum'][column_name])
            data.append(row)
        df = pd.DataFrame(data, columns=columns)
        sf = StyleFrame(df)
        sf.A_FACTOR = 4
        sf.to_excel(writer, sheet_name=role, best_fit=columns)


def dump_captains_to_excel(writer, fantasy_points, pro_players):
    captains_info = []
    for role in ['carry', 'mid', 'offlane', 'support']:
        for player_name in fantasy_points[role]:
            captains_info.append([player_name, pro_players[player_name]['team'], pro_players[player_name]['cost'], fantasy_points[role][player_name]['total points'] * 2, role])
    captains_info = sorted(captains_info, key=lambda x: x[3], reverse=True)

    columns = ['name', 'team', 'cost', 'points', 'role']
    df = pd.DataFrame(captains_info, columns=columns)
    sf = StyleFrame(df)
    sf.A_FACTOR = 4
    sf.to_excel(writer, sheet_name='captains rating', best_fit=columns)


def calculate_team_points(players_points, pro_players, players_names, captain_name):
    team_info = {'cost': 0, 'points': 0}
    positions_names = ['carry', 'mid', 'offlane', 'support 1', 'support 2']
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
    columns = ['carry', 'mid', 'offlane', 'support 1', 'support 2', 'cost', 'points']
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


def dump_records(players_points, pro_players, players_names, captain_name):
    team_info = {'cost': 0, 'points': 0}
    positions_names = ['carry', 'mid', 'offlane', 'support 1', 'support 2']
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


def dump_day(path, tournament_id, pro_players, reload_data, min_bound, max_bound, sort_key, balance):
    fantasy_points = compute_fantasy_points(tournament_id, pro_players, reload_data=reload_data, min_bound=min_bound, max_bound=max_bound)
    post_calculate_points(fantasy_points, pro_players)
    with pd.ExcelWriter(path) as writer:
        dump_points_to_excel(writer, fantasy_points, pro_players, sort_key)
        dump_captains_to_excel(writer, fantasy_points, pro_players)
        dump_teams_rating_to_excel(writer, fantasy_points, pro_players, count=1000, balance=balance)


def dump_overall_to_excel(writer, fantasy_points, pro_players, sorting_key):
    for role in ['carry', 'mid', 'offlane', 'support']:
        if len(fantasy_points[role]) == 0:
            continue

        role_points = dict(sorted(fantasy_points[role].items(), key=lambda x: x[1][sorting_key], reverse=True))
        data = list()
        main_columns = ['match count', 'total points', 'mean points per match', 'mean points per win',
                        'mean points per lose', 'mean per cost', 'mean duration', 'mean per duration', 'min points', 'max points', 'match points']
        columns = ['name', 'team', 'cost'] + main_columns
        for player_name in role_points:
            player_info = role_points[player_name]
            row = [player_name, pro_players[player_name]['team'], pro_players[player_name]['cost']]
            for column_name in main_columns:
                row.append(player_info[column_name])
            data.append(row)
        df = pd.DataFrame(data, columns=columns)
        sf = StyleFrame(df)
        sf.A_FACTOR = 4
        sf.apply_column_style(
            cols_to_style=['match points'],
            styler_obj=Styler(font='Courier New', horizontal_alignment=utils.horizontal_alignments.left),
        )
        sf.to_excel(writer, sheet_name=role, best_fit=columns)


def dump_overall(path: str, pro_players: dict, fantasy_points: dict, sort_key: str):
    with pd.ExcelWriter(path) as writer:
        dump_overall_to_excel(writer, fantasy_points, pro_players, sort_key)


def dump_overalls(path: str, name_prefix: str, tournament_id: int, pro_players: dict, reload_data: bool, min_bound: int, max_bound: int) -> dict:
    fantasy_points = compute_fantasy_points(tournament_id, pro_players, reload_data=reload_data, min_bound=min_bound, max_bound=max_bound)
    post_calculate_points(fantasy_points, pro_players)
    dump_overall(f'{path}/{name_prefix}overall.xlsx', pro_players, fantasy_points, 'mean points per match')
    dump_overall(f'{path}/{name_prefix}overall_sort_by_win.xlsx', pro_players, fantasy_points, 'mean points per win')
    dump_overall(f'{path}/{name_prefix}overall_sort_by_lose.xlsx', pro_players, fantasy_points, 'mean points per lose')
    return fantasy_points


def dump_overalls_by_points(path: str, name_prefix: str, pro_players: dict, fantasy_points: dict) -> dict:
    dump_overall(f'{path}/{name_prefix}overall.xlsx', pro_players, fantasy_points, 'mean points per match')
    dump_overall(f'{path}/{name_prefix}overall_sort_by_win.xlsx', pro_players, fantasy_points, 'mean points per win')
    dump_overall(f'{path}/{name_prefix}overall_sort_by_lose.xlsx', pro_players, fantasy_points, 'mean points per lose')
    return fantasy_points


def dump_tournament(name: str, tournament_id: int, reload: bool, play_off_first_match: int, days: list, balances: list = None) -> dict:
    output_path = f'dota2_fantasy/{name}'
    Path(output_path).mkdir(parents=True, exist_ok=True)

    pro_players = get_pro_players('pro_players.json')
    days = [1] + days + [9999999999]
    for day_num in range(1, len(days) - 1):
        balance = 100 if balances is None else balances[day_num - 1]
        dump_day(f'{output_path}/day{day_num}.xlsx', tournament_id, pro_players, reload, days[day_num], days[day_num + 1], 'total points', balance)

    pro_players_actual = get_pro_players('pro_players_actual.json')
    if play_off_first_match:
        dump_overalls(output_path, 'groups_', tournament_id, pro_players_actual, reload, 1, play_off_first_match)
        dump_overalls(output_path, 'playoff_', tournament_id, pro_players_actual, reload, play_off_first_match, 9999999999)

    return dump_overalls(output_path, '', tournament_id, pro_players_actual, reload, 1, 9999999999)


def merge_dicts(dict1, dict2, excluded_keys):
    merged_dict = {}
    for key in set(dict1) | set(dict2):
        if key in dict1 and key in dict2:
            if isinstance(dict1[key], dict) and isinstance(dict2[key], dict):
                merged_dict[key] = dict(merge_dicts(dict1[key], dict2[key], excluded_keys))
            else:
                if key not in excluded_keys:
                    merged_dict[key] = dict1[key] + dict2[key]
                else:
                    merged_dict[key] = dict2[key]
        elif key in dict1:
            merged_dict[key] = dict1[key]
        else:
            merged_dict[key] = dict2[key]
    return merged_dict


def merge_overalls(overalls: list[dict]) -> dict:
    overall_fantasy_points = overalls[0].copy()
    for fantasy_points in overalls[1:]:
        overall_fantasy_points = dict(merge_dicts(overall_fantasy_points, fantasy_points, ['team']))

    return overall_fantasy_points


def main():
    overalls = [
        # dump_tournament('7.35d-esl-one-birmingham-2024', 16518, False, 7704010804, []),
        # dump_tournament('7.35d-pgl-wallachia-2024', 16669, False, 7739857156, [7739857156, 7741332700, 7742965164, 7744813911]),
        # dump_tournament('7.35d–7.36-dreamleague-season-23', 16632, False, 7751224080, [7751224080, 7753420462, 7755832761, 7758350202]),
        # dump_tournament('7.36c-1win-series', 16427, False, 0, []),
        # dump_tournament('7.36c-road-to-the-international-2024-we', 16842, False, 0, []),
        dump_tournament('7.36c-riyadh-masters-2024', 16881, False, 0, []),
        dump_tournament('7.36c–7.37-elite-league-season-2', 16905, False, 0, []),
        dump_tournament('7.36c–7.37-snow-ruyi', 16901, False, 0, []),
        dump_tournament('7.37b-fissure-universe-episode-3', 16846, False, 0, []),
        dump_tournament('7.37c-the-international-2024', 16935, True, 0,
                        [7927665226, 7928915377, 7930304864, 7931849156, 7933465064, 7935041049, 7936398486, 7940501580, 7941965902, 7943623713],
                        [100, 100, 100, 100, 100, 100, 100, 110, 120, 120])
    ]

    pro_players_actual = get_pro_players('pro_players_actual.json')

    overall_fantasy_points = merge_overalls(overalls)
    post_calculate_points(overall_fantasy_points, pro_players_actual)
    dump_overalls_by_points('dota2_fantasy/', '', pro_players_actual, overall_fantasy_points)


def convert_pro_players_from_cyber():
    cyber_file_name = 'pro_players2.json'
    pro_players_file_name = 'pro_players.json'
    with open(cyber_file_name, 'r', encoding='utf8') as read_file:
        pro_players = {}
        for line in read_file.readlines():
            row = line.split('\t')
            print(row)
            pro_players[row[0]] = {'team': row[1], 'role': row[2], 'cost': int(row[3]), 'account_id': 0}

        with open(pro_players_file_name, 'w', encoding='utf8') as write_file:
            json.dump(pro_players, write_file, indent=2)


def calculate_table_ties(table, matches):
    values = [0, 1, 2]
    combinations = itertools.product(values, repeat=len(matches))
    results = table.copy()
    results_weighted = table.copy()
    for team in results:
        results[team] = 0
        results_weighted[team] = 0

    combinations_count = 0
    for combination in combinations:
        combinations_count += 1
        combination_table = table.copy()
        probability = 1.00
        for index, value in enumerate(combination):
            match = matches[index]
            if value == 0:
                combination_table[match['teams'][0]] += 2
            elif value == 1:
                combination_table[match['teams'][0]] += 1
                combination_table[match['teams'][1]] += 1
            elif value == 2:
                combination_table[match['teams'][1]] += 2

            probability *= match['probabilities'][value]

        combination_table = dict(sorted(combination_table.items(), key=lambda x: x[1], reverse=True))
        table_values = list(combination_table.values())
        if table_values[0] == table_values[1]:
            for team, value in combination_table.items():
                if value == table_values[0]:
                    results[team] += 1
                    results_weighted[team] += probability

        if table_values[1] == table_values[2]:
            if table_values[0] == table_values[1]:
                continue

            for team, value in combination_table.items():
                if value == table_values[1]:
                    results[team] += 1
                    results_weighted[team] += probability

    teams_names = results.keys()
    results_values = list(results.values())
    weighted_results_values = list(results_weighted.values())
    for i, team_name in enumerate(teams_names):
        print(f'{team_name}: by combinations: {results_values[i] / combinations_count * 100:.0f}% ({results_values[i]} of {combinations_count}), by BetBoom coeffs: {weighted_results_values[i] * 100:.0f}%')


def calculate_probabilities(matches):
    for match in matches:
        match['probabilities'] = []
        margin = 0.00
        for coefficient in match['coefficients']:
            margin += 1.00 / coefficient
        margin -= 1.00
        for coefficient in match['coefficients']:
            match['probabilities'].append(1.00 / coefficient - margin / len(match['coefficients']))


def calculate_ties():
    table_a = {
        'XG': 4,
        'GG': 2,
        'Heroic': 1,
        '1W': 1
    }

    matches_a = [
        {'teams': ['XG', '1W'], 'coefficients': [2.1, 2.35, 5.8]},
        {'teams': ['GG', 'Heroic'], 'coefficients': [1.8, 2.6, 7.0]}
    ]
    calculate_probabilities(matches_a)

    table_b = {
        'C9': 3,
        'G2.IG': 2,
        'Tundra': 2,
        'Talon': 1
    }

    matches_b = [
        {'teams': ['G2.IG', 'Tundra'], 'coefficients': [5.3, 2.0, 2.7]},
        {'teams': ['Talon', 'C9'], 'coefficients': [7.5, 2.2, 2.05]}
    ]
    calculate_probabilities(matches_b)

    table_c = {
        'Zero': 3,
        'BB': 2,
        'Falcons': 2,
        'Nouns': 1
    }

    matches_c = [
        {'teams': ['BB', 'Falcons'], 'coefficients': [4.5, 2.15, 2.4]},
        {'teams': ['Nouns', 'Zero'], 'coefficients': [2.7, 2.1, 4.5]}
    ]
    calculate_probabilities(matches_c)

    table_d = {
        'Spirit': 4,
        'Liquid': 4,
        'Aurora': 0,
        'Beastcoast': 0
    }

    matches_d = [
        {'teams': ['Liquid', 'Spirit'], 'coefficients': [4.2, 2.1, 2.7]},
        {'teams': ['Beastcoast', 'Aurora'], 'coefficients': [6.0, 2.15, 2.15]}
    ]
    calculate_probabilities(matches_d)

    print('Group A')
    calculate_table_ties(table_a, matches_a)
    print('\nGroup B')
    calculate_table_ties(table_b, matches_b)
    print('\nGroup C')
    calculate_table_ties(table_c, matches_c)
    print('\nGroup D')
    calculate_table_ties(table_d, matches_d)


def count_valid_teams(pro_players_actual, carry_names, mid_names, offlane_names, support_names, max_cost):
    teams_count = 0
    for carry_name in carry_names:
        for mid_name in mid_names:
            for offlane_name in offlane_names:
                for comb in itertools.combinations(support_names, 2):
                    cost = pro_players_actual[carry_name]['cost'] + pro_players_actual[mid_name]['cost'] + pro_players_actual[offlane_name]['cost'] + sum(pro_players_actual[player]['cost'] for player in comb)
                    if cost <= max_cost:
                        teams_count += 1
    return teams_count


def print_balance_distribution():
    pro_players_actual = get_pro_players('pro_players_day.json')

    carry_names = [player_name for player_name, player_data in pro_players_actual.items() if player_data['role'] == 'carry' and 'save_as' not in player_data]
    mid_names = [player_name for player_name, player_data in pro_players_actual.items() if player_data['role'] == 'mid' and 'save_as' not in player_data]
    offlane_names = [player_name for player_name, player_data in pro_players_actual.items() if player_data['role'] == 'offlane' and 'save_as' not in player_data]
    support_names = [player_name for player_name, player_data in pro_players_actual.items() if player_data['role'] == 'support' and 'save_as' not in player_data]
    print(f'carry count = {len(carry_names)}')
    print(f'mid count = {len(mid_names)}')
    print(f'offlane count = {len(offlane_names)}')
    print(f'support count = {len(support_names)}')
    teams_count = len(carry_names) * len(mid_names) * len(offlane_names) * sum(1 for _ in itertools.combinations(support_names, 2))
    for balance in range(100, 200, 5):
        teams_count_for_balance = count_valid_teams(pro_players_actual, carry_names, mid_names, offlane_names, support_names, balance)
        print(f'{balance}: {teams_count_for_balance}/{teams_count} {round(1.0 * teams_count_for_balance / teams_count * 100, 3)}%')


if __name__ == '__main__':
    main()
