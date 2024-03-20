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

HLTV_URL = 'https://www.hltv.org'


def get_selenium_driver() -> uc.Chrome:
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument("--disable-gpu")
    driver = uc.Chrome(options=options, no_sandbox=False, user_multi_procs=True, use_subprocess=False)
    stealth(
        driver,
        languages=['en-US', 'en'],
        platform='Win32',
        fix_hairline=True,
    )

    return driver


def get_page(url: str) -> BeautifulSoup:
    driver = get_selenium_driver()
    driver.get(url)
    return BeautifulSoup(markup=driver.page_source, features='html.parser')


def get_soup(base_url: str, url: str, reload: bool = False) -> BeautifulSoup:
    cache_file_path = f"parsed_data/{url.replace('/', '_').replace('?', '_').replace('=', '_')[1:]}"

    if reload or not os.path.exists(cache_file_path):
        soup = get_page(f'{base_url}{url}')
        with open(cache_file_path, 'w', encoding='utf-8') as file:
            file.write(str(soup))
    else:
        with open(cache_file_path, 'r', encoding='utf-8') as file:
            page_source = file.read()
            soup = BeautifulSoup(markup=page_source, features='html.parser')

    return soup


def get_matches(event_id: int, reload: bool):
    event_soup = get_soup(HLTV_URL, f'/results?event={event_id}', reload)
    matches = []
    for match_div in event_soup.find_all('div', 'result-con'):
        url = match_div.find('a').get('href')
        match_data = {'url': url, 'id': int(url.split('/')[2])}
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


def parse_match(match: dict):
    match_soup = get_soup(HLTV_URL, match['url'])
    match['details_url'] = match_soup.find('div', 'stats-detailed-stats').find('a').get('href')
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


def parse_event(event_id: int, reload: bool) -> dict:
    matches = get_matches(event_id, reload)
    for match in matches:
        parse_match(match)

    return {'matches': matches}


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


def get_pro_players() -> dict:
    with open('pro_players.json', 'r', encoding='utf8') as file:
        return json.load(file)


def create_fantasy_points_template(pro_players):
    fantasy_points = {'rifler': {}, 'sniper': {}}
    for player_name in pro_players:
        role = pro_players[player_name]['role']
        fantasy_points[role][player_name] = {
            'team': pro_players[player_name]['team'],
            'fantasy points': [],
            'points': [],
            'points details': [],
            'points details sum': dict()
        }

    return fantasy_points


def calculate_map_points(player_stat: dict, maps_num: int):
    return {
        'kills': player_stat['kills'],
        'assists': (player_stat['assists'] - player_stat['flashes']) * 0.6,
        'flashes': player_stat['flashes'] * 0.2,
        'deaths': (12 * maps_num - player_stat['deaths']) * 0.6,
        'fkdiff': 0 if player_stat['fkdiff'] < 0 else player_stat['fkdiff'] * 0.75
    }


def compute_fantasy_points(event_data: dict, pro_players: dict, min_bound: int, max_bound: int) -> dict:
    fantasy_points = create_fantasy_points_template(pro_players)
    for match in event_data['matches']:
        if not min_bound <= match['id'] < max_bound:
            continue

        for player_name, player_stat in match['total']['players'].items():
            points_details = calculate_map_points(player_stat, match['maps_num'])

            role = pro_players[player_name]['role']
            player_info = fantasy_points[role][player_name]
            player_info['points details'].append(points_details)
            match_multiplier = 1 if match['maps_num'] <= 2 else 2. / 3.
            for key, value in points_details.items():
                player_info['points details sum'][key] = np.round(player_info['points details sum'].get(key, 0) + value * match_multiplier, 3)

            points_sum = sum(points_details.values())
            player_info['fantasy points'].append(np.round(points_sum * match_multiplier, 3))
            player_info['points'].append(np.round(points_sum, 3))

    for role in fantasy_points.keys():
        for player_name, player_info in list(fantasy_points[role].items()):
            if len(player_info['fantasy points']) == 0:
                del fantasy_points[role][player_name]

    return fantasy_points


def post_calculate_points(fantasy_points, pro_players):
    for role in fantasy_points.keys():
        for player_name, player_info in fantasy_points[role].items():
            player_info['day points'] = np.round(np.sum(player_info['fantasy points']), 3)
            # player_info['mean points per match'] = np.round(np.mean(player_info['points']), 3)

            # player_info['mean per cost'] = np.round(player_info['mean points per match'] / pro_players[player_name]['cost'], 3)
            player_info['match count'] = len(player_info['fantasy points'])


def dump_points_to_excel(writer, fantasy_points, sorting_key):
    for role in fantasy_points.keys():
        role_points = dict(sorted(fantasy_points[role].items(), key=lambda x: x[1][sorting_key], reverse=True))
        data = list()
        main_columns = ['team', 'day points', 'match count']
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
        sf.to_excel(writer, sheet_name=role, best_fit=columns)


def dump_captains_to_excel(writer, fantasy_points):
    captains_info = []
    for role in fantasy_points.keys():
        for player_name, player_info in fantasy_points[role].items():
            captains_info.append([player_name, player_info['day points'] * 2, role])
    captains_info = sorted(captains_info, key=lambda x: x[1], reverse=True)

    columns = ['name', 'points', 'role']
    df = pd.DataFrame(captains_info, columns=columns)
    sf = StyleFrame(df)
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


def generate_teams(fantasy_points, pro_players, teams_count, balance):
    dream_teams_rating = []
    teams_rating = []

    sorted_riflers_points = dict(sorted(fantasy_points['rifler'].items(), key=lambda x: x[1]['day points'], reverse=True))
    riflers_names = list(sorted_riflers_points.keys())
    sorted_sniper_points = dict(sorted(fantasy_points['sniper'].items(), key=lambda x: x[1]['day points'], reverse=True))
    snipers_names = list(sorted_sniper_points.keys())

    for riflers_combination in itertools.combinations(riflers_names, 4):
        for sniper_name in snipers_names:
            team_names = [sniper_name] + list(riflers_combination)
            players_points = [sorted_sniper_points[sniper_name]['day points']]
            for rifler_name in riflers_combination:
                players_points.append(sorted_riflers_points[rifler_name]['day points'])

            for captain_name in team_names:
                team_info = calculate_team_points(players_points, pro_players, team_names, captain_name)

                if len(dream_teams_rating) < teams_count:
                    dream_teams_rating.append(team_info)

                if team_info['cost'] <= balance:
                    teams_rating.append(team_info)
                    if len(teams_rating) == teams_count:
                        return [dream_teams_rating, teams_rating]

    return [dream_teams_rating, teams_rating]


def dump_teams_rating_to_excel(writer, fantasy_points, pro_players, teams_count, balance):
    dream_teams_rating, teams_rating = generate_teams(fantasy_points, pro_players, teams_count, balance)

    teams_rating = sorted(teams_rating, key=lambda x: x['points'], reverse=True)
    dream_teams_rating = sorted(dream_teams_rating, key=lambda x: x['points'], reverse=True)
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
        sf_top_teams_df.to_excel(writer, sheet_name='Top teams', best_fit=columns)

    top_dream_teams_data = list()

    for team_info in dream_teams_rating:
        row = list()
        for column_name in columns:
            row.append(team_info[column_name])
        top_dream_teams_data.append(row)

    top_dream_teams_df = pd.DataFrame(top_dream_teams_data, columns=columns)
    sf_top_dream_teams_df = StyleFrame(top_dream_teams_df)
    sf_top_dream_teams_df.to_excel(writer, sheet_name='Top dream teams', best_fit=columns)


def calculate_fantasy_points(pro_players: dict, event_data: dict, min_bound: int, max_bound: int) -> dict:
    fantasy_points = compute_fantasy_points(event_data, pro_players, min_bound=min_bound, max_bound=max_bound)
    post_calculate_points(fantasy_points, pro_players)
    return fantasy_points


def compute_overall_fantasy_points(event_data: dict) -> dict:
    fantasy_points = {}
    for match in event_data['matches']:
        for map_stat in match['maps']:
            for player_index, [player_name, player_stat] in enumerate(map_stat['players'].items()):
                if player_name not in fantasy_points:
                    fantasy_points[player_name] = {
                        'team': map_stat['team1_name'] if player_index < 5 else map_stat['team2_name'],
                        'points': [],
                        'points per round': [],
                        'maps points': ''
                    }

                points_details = calculate_map_points(player_stat, 1)
                points_sum = round(sum(points_details.values()), 3)
                fantasy_points[player_name]['points'].append(points_sum)
                fantasy_points[player_name]['points per round'].append(round(points_sum / map_stat['rounds'], 3))
                fantasy_points[player_name]['maps points'] += '{0: <7}'.format(points_sum)

    for player_name, player_info in fantasy_points.items():
        player_info['mean points'] = np.round(np.mean(player_info['points']), 3)
        player_info['mean points per round'] = np.round(np.mean(player_info['points per round']), 3)

    return fantasy_points


def dump_overall_to_excel(writer, fantasy_points, sort_key):
    fantasy_points = dict(sorted(fantasy_points.items(), key=lambda x: x[1][sort_key], reverse=True))
    data = list()
    main_columns = ['team', 'mean points', 'mean points per round', 'maps points']
    for player_name, player_info in fantasy_points.items():
        row = [player_name]
        for column_name in main_columns:
            row.append(player_info[column_name])
        data.append(row)

    columns = ['name'] + main_columns
    df = pd.DataFrame(data, columns=columns)
    sf = StyleFrame(df)
    sf.apply_column_style(
        cols_to_style=['maps points'],
        styler_obj=Styler(font = 'Courier New', horizontal_alignment=utils.horizontal_alignments.left),
    )
    sf.to_excel(writer, sheet_name=f'{sort_key}', best_fit=columns)


def dump_day(excel_file_name: str, pro_players: dict, fantasy_points: dict, sort_key: str, balance: int):
    with pd.ExcelWriter(excel_file_name) as writer:
        dump_points_to_excel(writer, fantasy_points, sort_key)
        dump_captains_to_excel(writer, fantasy_points)
        dump_teams_rating_to_excel(writer, fantasy_points, pro_players, teams_count=1000, balance=balance)


def dump_event(event_name: str, event_id: int, reload: bool, pro_players: dict, days_bounds: list):
    event_data = get_event_data(event_id, reload)

    Path(event_name).mkdir(parents=True, exist_ok=True)
    for day_num in range(1, len(days_bounds)):
        fantasy_points = calculate_fantasy_points(pro_players, event_data, days_bounds[day_num - 1], days_bounds[day_num])
        dump_day(f'{event_name}/day{day_num}.xlsx', pro_players, fantasy_points, 'day points', 100)

    overall_fantasy_points = compute_overall_fantasy_points(event_data)
    with pd.ExcelWriter(f'{event_name}/overall.xlsx') as writer:
        dump_overall_to_excel(writer, overall_fantasy_points, 'mean points')
        dump_overall_to_excel(writer, overall_fantasy_points, 'mean points per round')


def main():
    pro_players = get_pro_players()

    dump_event('pgl-cs2-major-copenhagen-2024-opening-stage', 7258, False, pro_players, [2370595, 2370611, 2370619, 9999999999])

    dump_event('pgl-cs2-major-copenhagen-2024', 7148, False, pro_players, [1, 9999999999])

    dump_event('pgl-cs2-major-copenhagen-2024-europe-rmr-a', 7259, False, pro_players, [])
    dump_event('pgl-cs2-major-copenhagen-2024-europe-rmr-b', 7577, False, pro_players, [])


if __name__ == '__main__':
    main()