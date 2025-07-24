import os
import time
from pathlib import Path
import itertools
import json
import requests
import numpy as np
import pandas as pd
from styleframe import StyleFrame, Styler, utils
import matplotlib.pyplot as plt


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
                        if rune in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']:
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

                    account_id = player['account_id']
                    if account_id not in account_id_mapping:
                        continue

                    player_name = account_id_mapping[account_id]

                    if player_name not in pro_players:
                        if player_name not in printed_names:
                            printed_names[player_name] = ''
                            team_name = match_info.get('dire_name' if player['team_number'] else 'radiant_name', 'not found')
                            print(f'{player_name} not in pro_players ({player['account_id']}); team {team_name}')

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
                series_counts[series_id] -= 1

    for role in ['carry', 'mid', 'offlane', 'support']:
        fantasy_points[role] = {k: v for k, v in fantasy_points[role].items() if len(v) > 0}

    return fantasy_points


def post_calculate_points(fantasy_points, pro_players):
    for role in ['carry', 'mid', 'offlane', 'support']:
        for player_name, player_info in list(fantasy_points[role].items()):
            if len(player_info['fantasy points']) == 0 or player_name not in pro_players:
                del fantasy_points[role][player_name]

        for player_name in fantasy_points[role]:
            player_info = fantasy_points[role][player_name]
            player_info['total points'] = np.round(np.sum(player_info['fantasy points']), 3)
            player_info['mean per match'] = np.round(np.mean(player_info['points']), 3)
            player_info['min points'] = np.round(np.min(player_info['points']), 3)
            player_info['max points'] = np.round(np.max(player_info['points']), 3)

            player_info['mean per win'] = 0
            player_info['mean per lose'] = 0
            for i, points in enumerate(player_info['points']):
                if player_info['wins'][i]:
                    player_info['mean per win'] += np.round(points / player_info['wins count'], 3)
                else:
                    player_info['mean per lose'] += np.round(points / player_info['loses count'], 3)

            player_info['mean per cost'] = np.round(player_info['mean per match'] / pro_players[player_name]['cost'], 3)
            player_info['mean duration'] = np.round(np.mean(player_info['durations']) / 60, 3)
            player_info['mean per duration'] = np.round(player_info['mean per match'] / player_info['mean duration'], 3)
            player_info['match count'] = len(player_info['fantasy points'])


def dump_points_to_excel(writer, fantasy_points, pro_players, sorting_key):
    for role in ['carry', 'mid', 'offlane', 'support']:
        if len(fantasy_points[role]) == 0:
            continue

        role_points = dict(sorted(fantasy_points[role].items(), key=lambda x: x[1][sorting_key], reverse=True))
        data = list()
        main_columns = ['total points', 'match count', 'mean per match', 'mean per win',
                        'mean per lose', 'mean per cost', 'mean duration', 'mean per duration']
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


def dump_teams_rating_to_excel(writer, fantasy_points, pro_players, count, balance, sort_key='total points', dump_dream=True):
    teams_rating = []

    pos4_names = list(fantasy_points['support'])
    for pos1 in fantasy_points['carry']:
        for pos2 in fantasy_points['mid']:
            for pos3 in fantasy_points['offlane']:
                for pos4_index, pos4 in enumerate(pos4_names):
                    for pos5_index in range(pos4_index + 1, len(pos4_names)):
                        pos5 = pos4_names[pos5_index]
                        players_names = [pos1, pos2, pos3, pos4, pos5]
                        players_points = [fantasy_points['carry'][pos1][sort_key], fantasy_points['mid'][pos2][sort_key],
                                          fantasy_points['offlane'][pos3][sort_key], fantasy_points['support'][pos4][sort_key],
                                          fantasy_points['support'][pos5][sort_key]]
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
        sf_top_teams_df.to_excel(writer, sheet_name=f'Top teams ({sort_key})', best_fit=columns)

    if dump_dream:
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
        sf_top_dream_teams_df.to_excel(writer, sheet_name=f'Top dream teams ({sort_key})', best_fit=columns)


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
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        dump_points_to_excel(writer, fantasy_points, pro_players, sort_key)
        dump_captains_to_excel(writer, fantasy_points, pro_players)
        dump_teams_rating_to_excel(writer, fantasy_points, pro_players, count=1000, balance=balance)


def dump_overall_to_excel(writer, fantasy_points, pro_players, sorting_key):
    for role in ['carry', 'mid', 'offlane', 'support']:
        main_columns = ['match count', 'total points', 'mean per match', 'mean per win',
                        'mean per lose', 'mean per cost', 'mean duration', 'mean per duration', 'min points', 'max points', 'match points']
        columns = ['name', 'team', 'cost'] + main_columns

        data = list()
        if len(fantasy_points[role]):
            role_points = dict(sorted(fantasy_points[role].items(), key=lambda x: x[1][sorting_key], reverse=True))
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


def dump_overall(path: str, pro_players: dict, fantasy_points: dict, sort_key: str, balance: int = 0):
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        dump_overall_to_excel(writer, fantasy_points, pro_players, sort_key)

        if balance:
            dump_teams_rating_to_excel(writer, fantasy_points, pro_players, 1000, balance, 'mean per match', False)
            dump_teams_rating_to_excel(writer, fantasy_points, pro_players, 1000, balance, 'mean per win', False)
            dump_teams_rating_to_excel(writer, fantasy_points, pro_players, 1000, balance, 'mean per lose', False)
            dump_teams_rating_to_excel(writer, fantasy_points, pro_players, 1000, balance, 'mean per duration', False)


def dump_overalls(path: str, name_prefix: str, tournament_id: int, pro_players: dict, reload_data: bool, min_bound: int, max_bound: int, re_dump: bool, balance: int = 0) -> dict:
    fantasy_points = compute_fantasy_points(tournament_id, pro_players, reload_data=reload_data, min_bound=min_bound, max_bound=max_bound)
    post_calculate_points(fantasy_points, pro_players)
    if re_dump:
        dump_overall(f'{path}/{name_prefix}overall.xlsx', pro_players, fantasy_points, 'mean per match', balance)
        dump_overall(f'{path}/{name_prefix}overall_sort_by_win.xlsx', pro_players, fantasy_points, 'mean per win', 0)
        dump_overall(f'{path}/{name_prefix}overall_sort_by_lose.xlsx', pro_players, fantasy_points, 'mean per lose', 0)
    return fantasy_points


def dump_overalls_by_points(path: str, name_prefix: str, pro_players: dict, fantasy_points: dict, balance: int = 0) -> dict:
    dump_overall(f'{path}/{name_prefix}overall.xlsx', pro_players, fantasy_points, 'mean per match', balance)
    dump_overall(f'{path}/{name_prefix}overall_sort_by_win.xlsx', pro_players, fantasy_points, 'mean per win', 0)
    dump_overall(f'{path}/{name_prefix}overall_sort_by_lose.xlsx', pro_players, fantasy_points, 'mean per lose', 0)

    return fantasy_points


def dump_tournament(name: str, tournament_id: int, reload: bool = False, play_off_first_match: int = 0, days: list = None, balances: list = None, re_dump: bool = False, last_day_only: bool = False) -> dict:
    output_path = f'dota2_fantasy/{name}'
    if re_dump:
        Path(output_path).mkdir(parents=True, exist_ok=True)
        pro_players = get_pro_players('pro_players.json')
        days = [1] + days + [9999999999]
        if last_day_only:
            day_num = len(days) - 2
            balance = 100 if balances is None else balances[day_num - 1]
            dump_day(f'{output_path}/day{day_num}.xlsx', tournament_id, pro_players, reload, days[day_num], days[day_num + 1], 'total points', balance)
        else:
            for day_num in range(1, len(days) - 1):
                balance = 100 if balances is None else balances[day_num - 1]
                dump_day(f'{output_path}/day{day_num}.xlsx', tournament_id, pro_players, reload, days[day_num], days[day_num + 1], 'total points', balance)

    pro_players_actual = get_pro_players('pro_players_actual.json')
    if play_off_first_match:
        dump_overalls(output_path, 'groups_', tournament_id, pro_players_actual, reload, 1, play_off_first_match, re_dump)
        dump_overalls(output_path, 'playoff_', tournament_id, pro_players_actual, reload, play_off_first_match, 9999999999, re_dump)

    print(f'dump: {name}')

    return dump_overalls(output_path, '', tournament_id, pro_players_actual, reload, 1, 9999999999, re_dump)


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
        dump_tournament('7.37e-esl-one-bangkok-2024-powered-by-intel', 17509),

        dump_tournament('7.37e-blast-slam-i', 17414),

        dump_tournament('7.37e-dreamleague-season-25-qualifiers-powered-by-intel', 17628),

        dump_tournament('7.37e-esl-one-raleigh-2025-qualifiers', 17629),

        dump_tournament('7.37e-fissure-playground-open-qualifiers', 17520),

        dump_tournament('7.37e-fissure-playground-closed-qualifiers-eeu', 17523),
        dump_tournament('7.37e-fissure-playground-closed-qualifiers-weu', 17524),
        dump_tournament('7.37e-fissure-playground-closed-qualifiers-americas', 17525),
        dump_tournament('7.37e-fissure-playground-closed-qualifiers-sea', 17526),
        dump_tournament('7.37e-fissure-playground-closed-qualifiers-china', 17527),

        dump_tournament('7.37e-fissure-playground-1-dota', 17588),

        dump_tournament('7.37e-pgl-wallachia-season-3-open-qualifiers', 17646),

        dump_tournament('7.37e-pgl-wallachia-season-3-na-closed-qualifiers', 17669),
        dump_tournament('7.37e-pgl-wallachia-season-3-sa-closed-qualifiers', 17670),
        dump_tournament('7.37e-pgl-wallachia-season-3-sea-closed-qualifiers', 17671),
        dump_tournament('7.37e-pgl-wallachia-season-3-cn-closed-qualifiers', 17672),
        dump_tournament('7.37e-pgl-wallachia-season-3-weu-closed-qualifiers', 17673),
        dump_tournament('7.37e-pgl-wallachia-season-3-eeu-closed-qualifiers', 17674),

        dump_tournament('7.37e-blast-slam-ii', 17417),

        dump_tournament('7.37e-fissure-universe-ep-4-open-qualifiers', 17761),

        dump_tournament('7.37e-pgl-wallachia-season-4-open-qualifiers', 17766),

        dump_tournament('7.37e-fissure-universe-ep-4-closed-qualifiers-eeu', 17767),
        dump_tournament('7.37e-fissure-universe-ep-4-closed-qualifiers-weu', 17768),
        dump_tournament('7.37e-fissure-universe-ep-4-closed-qualifiers-na', 17769),
        dump_tournament('7.37e-fissure-universe-ep-4-closed-qualifiers-sa', 17770),
        dump_tournament('7.37e-fissure-universe-ep-4-closed-qualifiers-sea', 17771),
        dump_tournament('7.37e-fissure-universe-ep-4-closed-qualifiers-china', 17772),

        dump_tournament('7.37e-pgl-wallachia-season-4-eeu-closed-qualifiers', 17774),
        dump_tournament('7.37e-pgl-wallachia-season-4-weu-closed-qualifiers', 17775),
        dump_tournament('7.37e-pgl-wallachia-season-4-sea-closed-qualifiers', 17776),
        dump_tournament('7.37e-pgl-wallachia-season-4-cn-closed-qualifiers', 17777),
        dump_tournament('7.37e-pgl-wallachia-season-4-amer-closed-qualifiers', 17778),

        dump_tournament('7.37e–7.38-dreamleague-season-25', 17765), #16.02 - 04.03

        dump_tournament('7.38b-pgl-wallachia-2025-season-3', 17891), # 09.03 - 17.03

        dump_tournament('7.38b-7.38с-fissure-universe-episode-4', 17907), # 22.03 - 30.03

        dump_tournament('7.38с-dreamleague-season-26-qualifiers', 17874), # 01.04 - 03.04

        dump_tournament('7.38с-fissure-special', 18046), # 05.04 - 13.04

        dump_tournament('7.38c-esl-one-raleigh-2025', 17795), # 07.04 - 13.04

        dump_tournament('7.38c-pgl-wallachia-2025-season-4', 18058), # 19.04 - 27.04

        dump_tournament('7.38c-slam-iii', 17418), # 06.05 - 11.05

        dump_tournament('7.38c–7.39b-dreamleague-season-26', 18111), # 19.05 - 01.06

        dump_tournament('7.39c-esports-world-cup-2025-qualifiers', 18210), # 05.06 - 13.06

        dump_tournament('7.39c-pgl-wallachia-2025-season-5', 18358), # 21.06 - 29.06

        dump_tournament('7.39c-esports-world-cup-2025', 18375, True, 0,
                        [1, 8367368038, 8368604072, 8369831173, 8371179457, 8372628095, 8376447504, 8377669081, 8378959607, 8380303096],
                        [100, 100, 100, 100, 100, 100, 110, 110, 120, 120], True, True)
    ]
    re_dump = True
    if re_dump:
        pro_players_day = get_pro_players('pro_players_day.json')
        balance = 120
        overall_fantasy_points = merge_overalls(overalls)
        post_calculate_points(overall_fantasy_points, pro_players_day)
        dump_overalls_by_points('dota2_fantasy/', '', pro_players_day, overall_fantasy_points, balance)
        overall_fantasy_points =  merge_overalls(overalls[-34:])
        post_calculate_points(overall_fantasy_points, pro_players_day)
        dump_overalls_by_points('dota2_fantasy/', 'post_fissure_playground_', pro_players_day, overall_fantasy_points, balance)
        overall_fantasy_points =  merge_overalls(overalls[-26:])
        post_calculate_points(overall_fantasy_points, pro_players_day)
        dump_overalls_by_points('dota2_fantasy/', 'post_blast_slam_', pro_players_day, overall_fantasy_points, balance)
        overall_fantasy_points =  merge_overalls(overalls[-13:])
        post_calculate_points(overall_fantasy_points, pro_players_day)
        dump_overalls_by_points('dota2_fantasy/', 'post_7.38_', pro_players_day, overall_fantasy_points, balance)
        overall_fantasy_points =  merge_overalls(overalls[-9:])
        post_calculate_points(overall_fantasy_points, pro_players_day)
        dump_overalls_by_points('dota2_fantasy/', 'post_april_', pro_players_day, overall_fantasy_points, balance)
        overall_fantasy_points =  merge_overalls(overalls[-4:])
        post_calculate_points(overall_fantasy_points, pro_players_day)
        dump_overalls_by_points('dota2_fantasy/', 'post_7.39_', pro_players_day, overall_fantasy_points, balance)


def convert_pro_players_from_cyber():
    cyber_file_name = 'pro_players2.json'
    pro_players_file_name = 'pro_players.json'
    with open(cyber_file_name, 'r', encoding='utf8') as read_file:
        pro_players = {}
        for line in read_file.readlines():
            row = line.split('\t')
            print(row)
            pro_players[row[1]] = {'team': row[2], 'role': row[3], 'cost': int(row[4]), 'account_id': 0}

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

    combo_probability = 0
    for combination in combinations:
        combinations_count += 1
        combination_table = table.copy()
        probability = 1.00
        for index, value in enumerate(combination):
            match = matches[index]
            if value == 0:
                combination_table[match['teams'][0]] += 2
                # print(f'{match['teams'][0]} {match['teams'][1]} 2:0')
            elif value == 1:
                combination_table[match['teams'][0]] += 1
                combination_table[match['teams'][1]] += 1
                # print(f'{match['teams'][0]} {match['teams'][1]} 1:1')
            elif value == 2:
                combination_table[match['teams'][1]] += 2
                # print(f'{match['teams'][0]} {match['teams'][1]} 0:2')

            probability *= match['probabilities'][value]

        combination_table = dict(sorted(combination_table.items(), key=lambda x: x[1], reverse=True))
        table_values = list(combination_table.values())

        # print(combination_table)
        teams = {}
        if table_values[0] == table_values[1]:
            for team, value in combination_table.items():
                if value == table_values[0]:
                    teams[team] = True
                    # print(team)
                    results[team] += 1
                    results_weighted[team] += probability

        if table_values[1] == table_values[2]:
            if table_values[2] == table_values[0]:
                continue

            for team, value in combination_table.items():
                if value == table_values[2]:
                    teams[team] = True
                    # print(team)
                    results[team] += 1
                    results_weighted[team] += probability
        # if 'Avulus' in teams and 'Tundra' in teams:
        #     print('+')
        #     combo_probability += probability
        # print('\n')

    # print(combo_probability)

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
        'NAVI': 3,
        'Spirit': 3,
        'Talon': 1,
        'Extreme': 1
    }

    matches_a = [
        {'teams': ['Talon', 'Extreme'], 'coefficients': [4.80, 2.25, 2.50]},
        {'teams': ['Spirit', 'NAVI'], 'coefficients': [1.98, 2.40, 8.00]}
    ]
    calculate_probabilities(matches_a)

    print('Group A')
    calculate_table_ties(table_a, matches_a)

    table_b = {
        'BB': 3,
        'GG': 3,
        'Exectration': 1,
        'Falcons': 1
    }

    matches_b = [
        {'teams': ['BB', 'Exectration'], 'coefficients': [1.45, 3.6, 11.00]},
        {'teams': ['Falcons', 'GG'], 'coefficients': [4.2, 1.98, 3.4]},
    ]
    calculate_probabilities(matches_b)

    print('\nGroup B')
    calculate_table_ties(table_b, matches_b)

    table_c = {
        'Aurora': 3,
        'Tundra': 3,
        'Yandex': 2,
        'VP': 0
    }

    matches_c = [
        {'teams': ['Tundra', 'Yandex'], 'coefficients': [1.65, 2.9, 11.00]},
        {'teams': ['Aurora', 'VP'], 'coefficients': [1.70, 2.90, 9.00]}
    ]
    calculate_probabilities(matches_c)

    print('\nGroup C')
    calculate_table_ties(table_c, matches_c)

    table_d = {
        'Liquid': 4,
        'PVision': 2,
        'Heroic': 2,
        'Shopify': 0
    }

    matches_d = [
        {'teams': ['Liquid', 'Heroic'], 'coefficients': [1.82, 2.70, 8.00]},
        {'teams': ['PVision', 'Shopify'], 'coefficients': [1.40, 3.80, 12.00]},
    ]
    calculate_probabilities(matches_d)

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
                        # if carry_name == 'Satanic' and mid_name == "No[o]ne-":
                        #     if  pro_players_actual[mid_name]['team'] != "Spirit" and pro_players_actual[offlane_name]['team'] != "Spirit" and pro_players_actual[comb[0]]['team'] != "Spirit" and + pro_players_actual[comb[1]]['cost']:
                        #     # print(f'{carry_name} {mid_name} {offlane_name} {comb[0]} {comb[1]}')
                        #         teams_count += 1
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
    for balance in range(110, 140, 1):
        teams_count_for_balance = count_valid_teams(pro_players_actual, carry_names, mid_names, offlane_names, support_names, balance)
        print(f'{balance}: {teams_count_for_balance}/{teams_count} {round(1.0 * teams_count_for_balance / teams_count * 100, 3)}%')


if __name__ == '__main__':
    while True:
        main()
        print('iteration complete')
        time.sleep(300)

    main()
