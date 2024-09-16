import itertools
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from selenium_stealth import stealth
import undetected_chromedriver as uc
from styleframe import StyleFrame, Styler, utils
import multiprocessing
import concurrent.futures

HLTV_URL = 'https://www.hltv.org'


def get_selenium_driver() -> uc.Chrome:
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-renderer-backgrounding')
    driver_executable_path = f'{Path.home()}/appdata/roaming/undetected_chromedriver/undetected_chromedriver.exe'
    driver = uc.Chrome(driver_executable_path=driver_executable_path, options=options, no_sandbox=False, user_multi_procs=False, use_subprocess=False)
    stealth(
        driver,
        languages=['en-US', 'en'],
        platform='Win32',
        fix_hairline=True,
    )

    return driver


def get_page(url: str) -> BeautifulSoup:
    print(f'load: {url}')
    driver = get_selenium_driver()
    driver.get(url)
    soup = BeautifulSoup(markup=driver.page_source, features='lxml')
    driver.close()
    driver.quit()

    return soup


def get_soup(base_url: str, url: str, reload: bool = False) -> BeautifulSoup:
    cache_file_path = f"parsed_data/{url.replace('/', '_').replace('?', '_').replace('=', '_')[1:]}"

    if reload or not os.path.exists(cache_file_path):
        soup = get_page(f'{base_url}{url}')
        with open(cache_file_path, 'w', encoding='utf-8') as file:
            file.write(str(soup))
    else:
        with open(cache_file_path, 'r', encoding='utf-8') as file:
            page_source = file.read()
            soup = BeautifulSoup(markup=page_source, features='lxml')

    return soup


def get_matches(event_id: int, reload: bool):
    event_soup = get_soup(HLTV_URL, f'/results?event={event_id}', reload)
    matches = []
    for day_div in event_soup.find_all('div', 'results-sublist'):
        for match_div in day_div.find_all('div', 'result-con'):
            url = match_div.find('a').get('href')
            match_data = {'url': url, 'id': int(url.split('/')[2]), 'day': day_div.find('div', 'standard-headline').text}
            matches.append(match_data)

    return sorted(matches, key=lambda x: x['url'])


def get_map_stats(details_soup: BeautifulSoup) -> dict:
    map_stats = dict()

    map_info_soup = details_soup.find('div', 'match-info-box')
    map_info_strings = map_info_soup.text.split('\n')
    map_stats['name'] = map_info_strings[2]
    map_stats['team1_name'] = map_info_strings[3].strip()
    map_stats['team1_rounds'] = int(map_info_strings[4])
    map_stats['team2_name'] = map_info_strings[6]
    map_stats['team2_rounds'] = int(map_info_strings[7])
    map_stats['rounds'] = map_stats['team1_rounds'] + map_stats['team2_rounds']

    map_stats['players'] = {}
    for table_soup in details_soup.find_all('table', 'totalstats'):
        for row_soup in table_soup.find_all('tr')[1:]:
            player_stats = {
                'kills': int(row_soup.find('td', 'st-kills').text.split(' ')[0]),
                'assists': int(row_soup.find('td', 'st-assists').text.split(' ')[0]),
                'flashes': int(row_soup.find('td', 'st-assists').text.split(' ')[1].replace('(', '').replace(')', '')),
                'deaths': int(row_soup.find('td', 'st-deaths').text),
                'fkdiff': int(row_soup.find('td', 'st-fkdiff').text)
            }

            player_name = row_soup.find('td', 'st-player').find('a').text
            map_stats['players'][player_name] = player_stats

    return map_stats


def parse_match(match: dict) -> bool:
    match_soup = get_soup(HLTV_URL, match['url'])
    detailed_stats_div = match_soup.find('div', 'stats-detailed-stats')
    if detailed_stats_div is None:
        print(f'filtered: {match["url"]}')
        return False

    match['details_url'] = detailed_stats_div.find('a').get('href')

    details_soup = get_soup(HLTV_URL, match['details_url'])

    match['total'] = get_map_stats(details_soup)
    match['maps'] = []
    maps_soup = details_soup.findAll('a', 'stats-match-map')
    if maps_soup:
        for map_soup in maps_soup[1:]:
            map_url = map_soup.get('href')
            map_soup = get_soup(HLTV_URL, map_url)
            match['maps'].append(get_map_stats(map_soup))
    else:
        match['maps'].append(match['total'])

    match['maps_num'] = len(match['maps'])

    return True


def parse_event(event_id: int, reload: bool) -> dict:
    # matches = get_matches(event_id, reload)
    # approved_matches = []
    # for match in matches:
    #     if parse_match(match):
    #         approved_matches.append(match)
    #
    # return {'matches': approved_matches}

    matches = get_matches(event_id, reload)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = list(executor.map(parse_match, matches))
        return {'matches': [match for match, approved in zip(matches, results) if approved]}


def get_event_data(event_id: int, reload: bool):
    Path('parsed_data').mkdir(parents=True, exist_ok=True)
    statistic_cache_file_path = f'parsed_data/event_{event_id}_statistic.json'
    if reload or not os.path.exists(statistic_cache_file_path):
        event_data = parse_event(event_id, reload)

        with open(statistic_cache_file_path, 'w', encoding='utf8') as file:
            json.dump(event_data, file, indent=2)

        return event_data
    else:
        with open(statistic_cache_file_path, 'r', encoding='utf8') as file:
            return json.load(file)


def convert_pro_players_from_cyber():
    cyber_file_name = 'pro_players2.json'
    pro_players_file_name = 'pro_players.json'
    with open(cyber_file_name, 'r', encoding='utf8') as read_file:
        pro_players = {}
        for line in read_file.readlines():
            row = line.split('\t')
            print(row)
            pro_players[row[1]] = {'team': row[0], 'role': row[2], 'cost': int(row[3])}

        with open(pro_players_file_name, 'w', encoding='utf8') as write_file:
            json.dump(pro_players, write_file, indent=2)


def create_pro_players_template(event_data: dict):
    pro_players = {}
    for match in event_data['matches']:
        for player_name in match['total'].keys():
            pro_players[player_name] = {'role': 'rifler', 'cost': 10}

    with open('pro_players.json', 'w', encoding='utf8') as file:
        json.dump(pro_players, file, indent=2)


def get_pro_players(file_name: str) -> dict:
    with open(file_name, 'r', encoding='utf8') as file:
        return json.load(file)


def create_fantasy_points_template(pro_players):
    fantasy_points = {'rifler': {}, 'sniper': {}}
    for player_name in pro_players:
        role = pro_players[player_name]['role']
        fantasy_points[role][player_name] = {
            'team': pro_players[player_name]['team'],
            'maps num': 0,
            'fantasy points': [],
            'points': [],
            'points details': [],
            'points details sum': dict()
        }

    return fantasy_points


def calculate_map_points(player_stat: dict, maps_num: int):
    return {
        'kills': player_stat['kills'] * 2,
        'assists': (player_stat['assists'] - player_stat['flashes']) * 1.2,
        'flashes': player_stat['flashes'] * 0.4,
        'deaths': (12 * maps_num - player_stat['deaths']) * 1.2,
        'fkdiff': 0 if player_stat['fkdiff'] < 0 else player_stat['fkdiff'] * 1.5
    }


def compute_fantasy_points(event_data: dict, pro_players: dict, day: str) -> dict:
    fantasy_points = create_fantasy_points_template(pro_players)
    for match in event_data['matches']:
        if match['day'] != day:
            continue

        for player_name, player_stat in match['total']['players'].items():
            points_details = calculate_map_points(player_stat, match['maps_num'])
            points_details['fkdiff'] = 0
            for map_info in match['maps']:
                fk_diff = map_info['players'][player_name]['fkdiff']
                points_details['fkdiff'] += 0 if fk_diff < 0 else fk_diff * 1.5

            role = pro_players[player_name]['role']
            player_info = fantasy_points[role][player_name]
            player_info['points details'].append(points_details)
            player_info['maps num'] += match['maps_num']
            for key, value in points_details.items():
                player_info['points details sum'][key] = np.round(player_info['points details sum'].get(key, 0) + value / match['maps_num'], 3)

            points_sum = sum(points_details.values())
            player_info['fantasy points'].append(np.round(points_sum / match['maps_num'], 3))
            player_info['points'].append(np.round(points_sum, 3))

    for role in fantasy_points.keys():
        for player_name, player_info in list(fantasy_points[role].items()):
            if len(player_info['fantasy points']) == 0:
                del fantasy_points[role][player_name]

    return fantasy_points


def post_calculate_points(fantasy_points, pro_players):
    for role in fantasy_points.keys():
        for player_name, player_info in fantasy_points[role].items():
            player_info['cost'] = pro_players[player_name]['cost']
            player_info['total points'] = np.round(np.sum(player_info['fantasy points']), 3)
            player_info['points per cost'] = np.round(player_info['total points'] / pro_players[player_name]['cost'], 3)
            player_info['match num'] = len(player_info['fantasy points'])


def dump_points_to_excel(writer, fantasy_points, sorting_key):
    for role in fantasy_points.keys():
        role_points = dict(sorted(fantasy_points[role].items(), key=lambda x: x[1][sorting_key], reverse=True))
        data = list()
        main_columns = ['team', 'cost', 'total points', 'points per cost', 'match num', 'maps num']
        details_columns = ['kills', 'assists', 'flashes', 'deaths', 'fkdiff']
        for player_name, player_info in role_points.items():
            row = [player_name]
            for column_name in main_columns:
                row.append(player_info[column_name])
            for column_name in details_columns:
                row.append(player_info['points details sum'][column_name])
            data.append(row)

        columns = ['name'] + main_columns + details_columns
        df = pd.DataFrame(data, columns=columns)
        sf = StyleFrame(df)
        sf.A_FACTOR = 6
        sf.to_excel(writer, sheet_name=role, best_fit=columns)


def dump_captains_to_excel(writer, fantasy_points):
    captains_info = []
    for role in fantasy_points.keys():
        for player_name, player_info in fantasy_points[role].items():
            captains_info.append([player_name, player_info['total points'] * 2, role])
    captains_info = sorted(captains_info, key=lambda x: x[1], reverse=True)

    columns = ['name', 'points', 'role']
    df = pd.DataFrame(captains_info, columns=columns)
    sf = StyleFrame(df)
    sf.A_FACTOR = 4
    sf.to_excel(writer, sheet_name='captains rating', best_fit=columns)


def calculate_team_points(players_points, pro_players, players_names, captain_name):
    team_info = {'cost': 0, 'points': 0}
    positions_names = ['sniper', 'rifler1', 'rifler2', 'rifler3', 'rifler4']
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


def generate_teams(fantasy_points, pro_players, teams_count, balance, sort_key):
    dream_teams_rating = []
    teams_rating = []

    sorted_riflers_points = dict(sorted(fantasy_points['rifler'].items(), key=lambda x: x[1][sort_key], reverse=True))
    riflers_names = list(sorted_riflers_points.keys())
    sorted_sniper_points = dict(sorted(fantasy_points['sniper'].items(), key=lambda x: x[1][sort_key], reverse=True))
    snipers_names = list(sorted_sniper_points.keys())

    for riflers_combination in itertools.combinations(riflers_names, 4):
        for sniper_name in snipers_names:
            team_names = [sniper_name] + list(riflers_combination)
            players_points = [sorted_sniper_points[sniper_name][sort_key]]
            for rifler_name in riflers_combination:
                players_points.append(sorted_riflers_points[rifler_name][sort_key])

            for captain_name in team_names:
                team_info = calculate_team_points(players_points, pro_players, team_names, captain_name)
                dream_teams_rating.append(team_info)
                if team_info['cost'] <= balance:
                    teams_rating.append(team_info)

    teams_rating = sorted(teams_rating, key=lambda x: x['points'], reverse=True)
    dream_teams_rating = sorted(dream_teams_rating, key=lambda x: x['points'], reverse=True)
    return [dream_teams_rating[:teams_count], teams_rating[:teams_count]]


def dump_teams_rating_to_excel(writer, fantasy_points, pro_players, teams_count, balance, sort_key):
    dream_teams_rating, teams_rating = generate_teams(fantasy_points, pro_players, teams_count, balance, sort_key)

    columns = ['sniper', 'rifler1', 'rifler2', 'rifler3', 'rifler4', 'cost', 'points']
    top_teams_data = list()
    for team_info in teams_rating:
        if team_info['cost'] <= balance:
            row = list()
            for column_name in columns:
                row.append(team_info[column_name])
            top_teams_data.append(row)

    if len(top_teams_data):
        top_teams_df = pd.DataFrame(top_teams_data, columns=columns)
        sf_top_teams_df = StyleFrame(top_teams_df)
        sf_top_teams_df.A_FACTOR = 4
        sf_top_teams_df.to_excel(writer, sheet_name='Top teams', best_fit=columns)

    top_dream_teams_data = list()

    for team_info in dream_teams_rating:
        row = list()
        for column_name in columns:
            row.append(team_info[column_name])
        top_dream_teams_data.append(row)

    top_dream_teams_df = pd.DataFrame(top_dream_teams_data, columns=columns)
    sf_top_dream_teams_df = StyleFrame(top_dream_teams_df)
    sf_top_dream_teams_df.A_FACTOR = 4
    sf_top_dream_teams_df.to_excel(writer, sheet_name='Top dream teams', best_fit=columns)


def calculate_fantasy_points(pro_players: dict, event_data: dict, day: str) -> dict:
    fantasy_points = compute_fantasy_points(event_data, pro_players, day)
    post_calculate_points(fantasy_points, pro_players)
    return fantasy_points


def compute_overall_fantasy_points(event_data: dict) -> dict:
    fantasy_points = {}
    for match in event_data['matches']:
        for map_stat in match['maps']:
            for player_index, [player_name, player_stat] in enumerate(map_stat['players'].items()):
                is_team1 = player_index < 5
                if player_name not in fantasy_points:
                    fantasy_points[player_name] = {
                        'team': map_stat['team1_name'] if is_team1 else map_stat['team2_name'],
                        'points': [],
                        'points per round': [],
                        'wins': [],
                        'wins count': 0,
                        'loses count': 0,
                        'rounds won': [],
                        'maps points': '',
                        'maps': {}
                    }
                player_info = fantasy_points[player_name]

                points_details = calculate_map_points(player_stat, 1)
                points_sum = round(sum(points_details.values()), 3)
                is_win = (map_stat['team1_rounds'] > map_stat['team2_rounds']) == is_team1
                rounds_won = (map_stat['team1_rounds'] if is_team1 else map_stat['team2_rounds']) / map_stat['rounds'] * 100
                player_info['points'].append(points_sum)
                player_info['points per round'].append(round(points_sum / map_stat['rounds'], 3))
                player_info['wins'].append(is_win)
                player_info['wins count' if is_win else 'loses count'] += 1
                player_info['rounds won'].append(rounds_won)
                player_info['maps points'] += '{0: <7}'.format(points_sum)

                if map_stat['name'] not in player_info['maps']:
                    player_info['maps'][map_stat['name']] = {
                        'points': [],
                        'points per round': [],
                        'wins': [],
                        'wins count': 0,
                        'loses count': 0,
                        'rounds won': [],
                        'map points': ''
                    }

                map_info = player_info['maps'][map_stat['name']]
                map_info['points'].append(points_sum)
                map_info['points per round'].append(round(points_sum / map_stat['rounds'], 3))
                map_info['wins'].append(is_win)
                map_info['wins count' if is_win else 'loses count'] += 1
                map_info['rounds won'].append(rounds_won)
                map_info['map points'] += '{0: <7}'.format(points_sum)
    return fantasy_points


def postproc_overall_fantasy_points(fantasy_points: dict):
    for player_info in fantasy_points.values():
        player_info['mean points'] = np.round(np.mean(player_info['points']), 3)
        player_info['mean points per win'] = 0
        player_info['mean points per lose'] = 0
        for i, points in enumerate(player_info['points']):
            if player_info['wins'][i]:
                player_info['mean points per win'] += np.round(points / player_info['wins count'], 3)
            else:
                player_info['mean points per lose'] += np.round(points / player_info['loses count'], 3)
        player_info['winrate'] = f'{np.round(player_info['wins count'] / len(player_info['points']) * 100, 1)}%'
        player_info['mean points per round'] = np.round(np.mean(player_info['points per round']), 3)
        player_info['mean points per cost'] = 0
        if 'cost' in player_info.keys():
            player_info['mean points per cost'] = np.round(player_info['mean points'] / player_info['cost'], 3)
        player_info['min points'] = np.round(min(player_info['points']), 3)
        player_info['max points'] = np.round(max(player_info['points']), 3)
        player_info['rounds winrate'] = f'{np.round(np.mean(player_info['rounds won']), 1)}%'

        mean_points = []
        for map_name, map_info in player_info['maps'].items():
            map_info['mean points'] = np.round(np.mean(map_info['points']), 3)
            map_info['mean points per win'] = 0
            map_info['mean points per lose'] = 0
            for i, points in enumerate(map_info['points']):
                if map_info['wins'][i]:
                    map_info['mean points per win'] += np.round(points / map_info['wins count'], 3)
                else:
                    map_info['mean points per lose'] += np.round(points / map_info['loses count'], 3)
            map_info['winrate'] = f'{np.round(map_info['wins count'] / len(map_info['points']) * 100, 1)}%'
            map_info['mean points per round'] = np.round(np.mean(map_info['points per round']), 3)
            map_info['min points'] = np.round(min(map_info['points']), 3)
            map_info['max points'] = np.round(max(map_info['points']), 3)
            map_info['rounds winrate'] = f'{np.round(np.mean(map_info['rounds won']), 1)}%'
            mean_points.append((map_name, map_info['mean points']))

        mean_points.sort(key=lambda x: x[1], reverse=True)
        map_ratings = {map_name: rank + 1 for rank, (map_name, _) in enumerate(mean_points)}
        for map_name in player_info['maps']:
            player_info['maps'][map_name]['map rating'] = map_ratings[map_name]


def dump_overall_to_excel(writer, fantasy_points, sort_key):
    fantasy_points = dict(sorted(fantasy_points.items(), key=lambda x: x[1][sort_key], reverse=True))
    data = list()
    main_columns = ['team', 'role', 'cost', 'mean points', 'mean points per win', 'mean points per lose', 'winrate', 'mean points per round', 'mean points per cost', 'min points', 'max points', 'rounds winrate', 'maps points']
    for player_name, player_info in fantasy_points.items():
        row = [player_name]
        for column_name in main_columns:
            if column_name in player_info.keys():
                row.append(player_info[column_name])
            else:
                row.append('')
        data.append(row)

    columns = ['name'] + main_columns
    df = pd.DataFrame(data, columns=columns)
    sf = StyleFrame(df)
    sf.A_FACTOR = 4
    sf.apply_column_style(
        cols_to_style=['maps points'],
        styler_obj=Styler(font='Courier New', horizontal_alignment=utils.horizontal_alignments.left),
    )
    sf.to_excel(writer, sheet_name=f'{sort_key}', best_fit=columns)


def dump_maps_perfomance_to_excel(writer, fantasy_points):
    maps_data = {}
    main_columns = ['team', 'role', 'cost']
    map_columns = ['map rating', 'mean points', 'mean points per win', 'mean points per lose', 'winrate', 'mean points per round', 'min points', 'max points', 'rounds winrate', 'map points']
    for player_name, player_info in fantasy_points.items():
        for map_name, map_info in player_info['maps'].items():
            if map_name not in maps_data:
                maps_data[map_name] = []

            row = [player_name]
            for column_name in main_columns:
                if column_name in player_info.keys():
                    row.append(player_info[column_name])
                else:
                    row.append('')

            for column_name in map_columns:
                row.append(map_info[column_name])

            maps_data[map_name].append(row)

    maps_data = dict(sorted(maps_data.items()))
    columns = ['name'] + main_columns + map_columns
    for map_name, map_data in maps_data.items():
        map_data = sorted(map_data, key=lambda x: x[5], reverse=True)
        df = pd.DataFrame(map_data, columns=columns)
        sf = StyleFrame(df)
        sf.A_FACTOR = 4
        sf.apply_column_style(
            cols_to_style=['map points'],
            styler_obj=Styler(font='Courier New', horizontal_alignment=utils.horizontal_alignments.left),
        )
        sf.to_excel(writer, sheet_name=map_name, best_fit=columns)


def dump_overall(excel_file_name: str, overall_fantasy_points: dict, pro_players: dict, balance: int):
    with pd.ExcelWriter(excel_file_name) as writer:
        for player_name, player_stat in overall_fantasy_points.items():
            if player_name in pro_players:
                player_stat['role'] = pro_players[player_name]['role']
                player_stat['cost'] = pro_players[player_name]['cost']

        dump_overall_to_excel(writer, overall_fantasy_points, 'mean points')
        dump_overall_to_excel(writer, overall_fantasy_points, 'mean points per win')
        dump_overall_to_excel(writer, overall_fantasy_points, 'mean points per lose')

        dump_maps_perfomance_to_excel(writer, overall_fantasy_points)

        fantasy_points_by_role = {'rifler': {}, 'sniper': {}}
        for player_name in pro_players:
            if player_name in overall_fantasy_points:
                role = pro_players[player_name]['role']
                fantasy_points_by_role[role][player_name] = overall_fantasy_points[player_name]

        if balance:
            dump_teams_rating_to_excel(writer, fantasy_points_by_role, pro_players, 1000, balance, 'mean points')


def dump_day(excel_file_name: str, pro_players: dict, fantasy_points: dict, sort_key: str, balance: int):
    with pd.ExcelWriter(excel_file_name) as writer:
        dump_points_to_excel(writer, fantasy_points, sort_key)
        dump_captains_to_excel(writer, fantasy_points)
        dump_teams_rating_to_excel(writer, fantasy_points, pro_players, 1000, balance, 'total points')


def dump_event(event_name: str, event_id: int, reload: bool, pro_players: dict, balance: int = 100, re_dump: bool = False, dump_days: bool = False, last_day_only: bool = False) -> dict:
    print(event_name)
    event_data = get_event_data(event_id, reload)

    output_path = f'cs2_fantasy/{event_name}'
    if re_dump:
        Path('cs2_fantasy').mkdir(parents=True, exist_ok=True)
        Path(output_path).mkdir(parents=True, exist_ok=True)

    if dump_days and re_dump:
        unique_days = set()
        for match in event_data['matches']:
            unique_days.add(match['day'])
        unique_days = sorted(list(unique_days))
        if last_day_only:
            unique_days = [list(unique_days)[-1]]

        for day in unique_days:
            fantasy_points = calculate_fantasy_points(pro_players, event_data, day)
            dump_day(f'{output_path}/{day}.xlsx', pro_players, fantasy_points, 'total points', balance)

    overall_fantasy_points = compute_overall_fantasy_points(event_data)
    postproc_overall_fantasy_points(overall_fantasy_points)
    if re_dump:
        dump_overall(f'{output_path}/overall.xlsx', overall_fantasy_points, pro_players, 0)
        print(f'dump: {event_name}')

    return overall_fantasy_points


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


def dump_merged_overalls(file_name: str, overalls: list[dict], pro_players: dict, balance: int) -> dict:
    output_path = f'cs2_fantasy'
    Path(output_path).mkdir(parents=True, exist_ok=True)

    overall_fantasy_points = merge_overalls(overalls)
    overall_fantasy_points = {key: value for key, value in overall_fantasy_points.items() if key in pro_players}

    postproc_overall_fantasy_points(overall_fantasy_points)
    dump_overall(f'{output_path}/{file_name}.xlsx', overall_fantasy_points, pro_players, balance)

    return overall_fantasy_points


def count_valid_teams(pro_players_actual, riflers_names, snipers_names, max_cost):
    teams_count = 0
    for comb in itertools.combinations(riflers_names, 4):
        for sniper_name in snipers_names:
            cost = sum(pro_players_actual[player]['cost'] for player in comb) + pro_players_actual[sniper_name]['cost']
            if cost <= max_cost:
                teams_count += 1
    return teams_count


def print_balance_distribution():
    pro_players_actual = get_pro_players('pro_players_day.json')

    snipers_names = [player_name for player_name, player_data in pro_players_actual.items() if player_data['role'] == 'sniper']
    riflers_names = [player_name for player_name, player_data in pro_players_actual.items() if player_data['role'] == 'rifler']
    print(f'snipers count = {len(snipers_names)}')
    print(f'riflers count = {len(riflers_names)}')
    teams_count = sum(1 for _ in itertools.combinations(riflers_names, 4)) * len(snipers_names)
    for balance in range(100, 200, 5):
        teams_count_for_balance = count_valid_teams(pro_players_actual, riflers_names, snipers_names, balance)
        print(f'{balance}: {teams_count_for_balance}/{teams_count} {round(1.0 * teams_count_for_balance / teams_count * 100, 3)}%')


def print_cost_distribution():
    pro_players_actual = get_pro_players('pro_players_actual.json')
    costs_distribution = {10: 0, 15: 0, 20: 0, 25: 0, 30: 0, 35: 0}
    for player_name in pro_players_actual:
        cost = pro_players_actual[player_name]['cost']
        costs_distribution[cost] = costs_distribution[cost] + 1
    print(costs_distribution)


def calculate_predict_points_for_map(result_points: dict, pro_players: dict, players: list, fantasy_points: dict, match: dict, win_points_key: str, lose_points_key: str):
    for player_name in players:
        player_role = pro_players[player_name]['role']
        if player_name not in result_points[player_role].keys():
            result_points[player_role][player_name] = {'points': 0}
        for map_index, map_result in enumerate(match['wins']):
            map_name = match['maps'][map_index]
            map_info = fantasy_points[player_name]['maps'][map_name]
            result_points[player_role][player_name]['points'] += map_info[win_points_key if map_result else lose_points_key] / len(match['wins'])


def print_predict(fantasy_points: dict, pro_players: dict, matches: list, balance: int):
    print('')
    result_points = {'rifler': {}, 'sniper': {}}
    for match in matches:
        team1_players = [player_name for player_name, player_info in pro_players.items() if player_info['team'] == match['team1_name']]
        calculate_predict_points_for_map(result_points, pro_players, team1_players, fantasy_points, match, 'mean points per win', 'mean points per lose')
        team2_players = [player_name for player_name, player_info in pro_players.items() if player_info['team'] == match['team2_name']]
        calculate_predict_points_for_map(result_points, pro_players, team2_players, fantasy_points, match, 'mean points per lose', 'mean points per win')

        for map_index, map_result in enumerate(match['wins']):
            map_name = match['maps'][map_index]
            print(f'{map_name} - {match['team1_name'] if map_result else match['team2_name']} won')

    print('')
    dream_teams_rating, teams_rating = generate_teams(result_points, pro_players, 20, balance, 'points')
    for role, role_info in result_points.items():
        print(role)
        role_info = dict(sorted(role_info.items(), key=lambda x: x[1]['points'], reverse=True))
        for player_name, player_info in role_info.items():
            print(f'{player_name} {player_info['points']:.3f}')
        print('')

    for team in teams_rating:
        print(f'{team['sniper']}\t{team['rifler1']}\t{team['rifler2']}\t{team['rifler3']}\t{team['rifler4']}\t{team['cost']}\t{team['points']:.3f}')


def main():
    pro_players = get_pro_players('pro_players.json')

    overalls = [
        dump_event('betboom-dacha-2023', 7499, False, pro_players),  # Dec 5th - Dec 10th 2023
        dump_event('pgl-cs2-major-copenhagen-2024-na-rmr-closed-qualifier', 7409, False, pro_players),  # Jan 12th - Jan 14th 2024
        dump_event('pgl-cs2-major-copenhagen-2024-europe-rmr-closed-qualifier-a', 7392, False, pro_players),  # Jan 18th - Jan 20th 2024
        dump_event('pgl-cs2-major-copenhagen-2024-europe-rmr-closed-qualifier-b', 7619, False, pro_players),  # Jan 18th - Jan 20th 2024
        dump_event('pgl-cs2-major-copenhagen-2024-east-asia-rmr-closed-qualifier', 7399, False, pro_players),  # Jan 19th - Jan 21st 2024
        dump_event('pgl-cs2-major-copenhagen-2024-sa-rmr-closed-qualifier', 7410, False, pro_players),  # Jan 19th - Jan 21st 2024
        dump_event('pgl-cs2-major-copenhagen-2024-europe-rmr-decider-qualifier', 7391, False, pro_players),  # Jan 21st 2024
        dump_event('blast-premier-spring-groups-2024', 7552, False, pro_players),  # Jan 22nd - Jan 28th 2024
        dump_event('iem-katowice-2024-play-in', 7551, False, pro_players),  # Jan 31st - Feb 2nd 2024
        dump_event('iem-katowice-2024', 7435, False, pro_players),  # Feb 3rd - Feb 11th 2024
        dump_event('pgl-cs2-major-copenhagen-2024-europe-rmr-a', 7259, False, pro_players),  # Feb 14th - Feb 17th 2024
        dump_event('pgl-cs2-major-copenhagen-2024-europe-rmr-b', 7577, False, pro_players),  # Feb 19th - Feb 22nd 2024
        dump_event('pgl-cs2-major-copenhagen-2024-asia-rmr', 7260, False, pro_players),  # Feb 26th - Feb 28th 2024
        dump_event('pgl-cs2-major-copenhagen-2024-americas-rmr', 7261, False, pro_players),  # Mar 1st - Mar 4th 2024
        dump_event('blast-premier-spring-showdown-2024', 7553, False, pro_players),  # Mar 6th - Mar 10th 2024
        dump_event('pgl-cs2-major-copenhagen-2024-opening-stage', 7258, False, pro_players),  # Mar 17th - Mar 20th 2024
        dump_event('pgl-cs2-major-copenhagen-2024', 7148, False, pro_players),  # Mar 21st - Mar 31st 2024
        dump_event('betboom-dacha-belgrade-2024-south-america-closed-qualifier', 7771, False, pro_players),  # Apr 4th - Apr 11th 2024
        dump_event('betboom-dacha-belgrade-2024-europe-closed-qualifier', 7757, False, pro_players),  # Apr 2nd - Apr 12th 2024
        dump_event('iem-chengdu-2024', 7437, False, pro_players),  # Apr 8th - Apr 14th 2024
        dump_event('skyesports-masters-2024', 7711, False, pro_players),  # Apr 8th - Apr 14th 2024
        dump_event('global-esports-tour-rio-2024', 7742, False, pro_players),  # Apr 18th - Apr 20th 2024
        dump_event('esl-challenger-melbourne-2024', 7600, False, pro_players),  # Apr 26th - Apr 28th 2024
        dump_event('cct-season-2-europe-series-1', 7781, False, pro_players),  # Apr 21st - May 4th 2024
        dump_event('cct-season-2-europe-series-2', 7795, False, pro_players),  # Apr 29th - May 12th 2024
        dump_event('esl-pro-league-season-19', 7440, False, pro_players),  # Apr 23rd - May 12th 2024
        dump_event('betboom-dacha-belgrade-2024', 7755, False, pro_players),  # May 14th - May 19th 2024
        dump_event('iem-dallas-2024', 7438, False, pro_players),  # May 27th - Jun 2nd 2024
        dump_event('blast-premier-spring-final-2024', 7485, False, pro_players),  # Jun 12th - Jun 16th 2024

        dump_event('cct-season-2-europe-series-6', 7899, False, pro_players),  # Jul 15th - Jul 28th 2024
        dump_event('cct-season-2-south-america-series-2', 7948, False, pro_players),  # Jul 15th - Aug 2nd 2024
        dump_event('esports-world-cup-2024', 7732, False, pro_players),  # Jul 17th - Jul 21st 2024
        dump_event('skyesports-championship-2024', 7847, False, pro_players),  # Jul 23rd - Jul 28th 2024
        dump_event('betboom-dacha-belgrade-season-2-south-america-closed-qualifier', 7994, False, pro_players),  # Jul 28th - Aug 3rd 2024
        dump_event('betboom-dacha-belgrade-season-2-europe-closed-qualifier', 7992, False, pro_players),  # Jul 28th - Aug 5th 2024
        dump_event('blast-premier-fall-groups-2024', 7554, False, pro_players),  # Jul 29th - Aug 4th 2024
        dump_event('iem-cologne-2024-play-in', 7675, False, pro_players),  # Aug 7th - Aug 9th 2024
        dump_event('iem-cologne-2024', 7436, True, pro_players, 110, True, True, True)  # Aug 10th - Aug 18th 2024
    ]

    overall_fantasy_points = dump_merged_overalls('overall', overalls, pro_players, 0)
    dump_merged_overalls('overall_post_july', overalls[-9:], pro_players, 0)
    dump_merged_overalls('overall_cologne', overalls[-2:], pro_players, 0)

    next_day_balance = 110
    pro_players_day = get_pro_players('pro_players_day.json')
    dump_merged_overalls('day_overall', overalls, pro_players_day, next_day_balance)
    dump_merged_overalls('day_overall_post_july', overalls[-9:], pro_players_day, next_day_balance)
    dump_merged_overalls('day_overall_cologne', overalls[-2:], pro_players_day, next_day_balance)
    matches = [
        {'team1_name': 'Vitality', 'team2_name': 'NAVI', 'maps': ['Nuke', 'Dust2', 'Mirage', 'Inferno'], 'wins': [True, False, True, True]}
    ]
    print_predict(overall_fantasy_points, pro_players, matches, 110)

if __name__ == '__main__':
    main()
